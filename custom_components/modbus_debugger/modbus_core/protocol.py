"""Modbus Protocol Handling (PDU parsing, CRC, Packet Building)."""


import struct
from .exceptions import ModbusInvalidResponseError, ModbusExceptionResponseError


def compute_crc(data: bytes) -> int:
    """Compute CRC16 for Modbus RTU."""
    crc = 0xFFFF
    for char in data:
        crc ^= char
        for _ in range(8):
            if crc & 0x0001:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc


def build_rtu_request(slave_id: int, function_code: int, data: bytes) -> bytes:
    """Build a Modbus RTU request frame."""
    packet = struct.pack(">B", slave_id) + struct.pack(">B", function_code) + data
    crc = compute_crc(packet)
    # CRC is Little Endian in Modbus
    return packet + struct.pack("<H", crc)


def build_tcp_request(
    transaction_id: int, slave_id: int, function_code: int, data: bytes
) -> bytes:
    """Build a Modbus TCP request frame."""
    # Transaction ID (2 bytes)
    # Protocol ID (2 bytes, 0 for Modbus)
    # Length (2 bytes, Slave ID + Func + Data)
    # Slave ID (1 byte)
    # Func (1 byte)
    # Data (N bytes)

    length = 1 + 1 + len(data)  # Slave ID + Func + Data
    header = struct.pack(">HHH", transaction_id, 0, length)
    body = struct.pack(">BB", slave_id, function_code) + data
    return header + body


def parse_mbap_header(header_data: bytes) -> tuple[int, int, int]:
    """Parse Modbus TCP Header (MBAP). Returns (transaction_id, protocol_id, length)."""
    if len(header_data) == 6:
        return struct.unpack(">HHH", header_data)
    if len(header_data) == 7:
        tid, pid, length, uid = struct.unpack(">HHHB", header_data)
        return tid, pid, length
    raise ModbusInvalidResponseError(
        f"MBAP header must be 6 or 7 bytes, got {len(header_data)}"
    )


def validate_rtu_crc(data: bytes) -> bool:
    """Validate CRC of a full RTU packet."""
    if len(data) < 4:
        return False
    msg = data[:-2]
    received_crc = struct.unpack("<H", data[-2:])[0]
    calculated_crc = compute_crc(msg)
    return received_crc == calculated_crc


def parse_response_pdu(data: bytes) -> tuple[int, bytes]:
    """Parse PDU (Function Code + Data). Checks for Exception."""
    if len(data) < 2:
        raise ModbusInvalidResponseError("Response too short")

    fc = data[0]
    # Check for Exception (High bit set)
    if fc & 0x80:
        exception_code = data[1]
        raise ModbusExceptionResponseError(exception_code)

    return fc, data[1:]


def check_gaps(data: bytes) -> str | None:
    """Scan returned bytes for large blocks of zeros or ones (Gap check)."""
    if len(data) <= 10:
        return None

    # Check for 10+ consecutive 0x00 or 0xFF
    zeros = b"\x00" * 10
    ones = b"\xff" * 10

    if zeros in data or ones in data:
        return "WARNING: Large block of zeros/ones detected. This might be an invalid 'Gap' read."
    return None


def validate_response(
    pdu_data: bytes,
    expected_count: int,
    sent_tid: int | None = None,
    raw_frame: bytes | None = None,
) -> list[str]:
    """
    Perform strict Modbus validation.
    pdu_data: The data part of the PDU (excluding Function Code).
              For reads, the first byte is the byte count.
    """
    violations = []

    # 1. Byte Count Check (For Read Functions)
    if len(pdu_data) < 1:
        violations.append("VIOLATION: Response PDU too short (missing byte count).")
        return violations

    claimed_byte_count = pdu_data[0]
    actual_data_len = len(pdu_data) - 1

    if claimed_byte_count != expected_count * 2:
        violations.append(
            f"VIOLATION: Byte Count Mismatch. Expected {expected_count * 2} bytes ({expected_count} regs), "
            f"Device claimed {claimed_byte_count} bytes. This will cause Home Assistant to timeout."
        )

    # 2. Actual Data Length Check
    if actual_data_len != claimed_byte_count:
        violations.append(
            f"VIOLATION: Payload Mismatch. Header claimed {claimed_byte_count} bytes, "
            f"but received {actual_data_len} bytes."
        )

    # 3. MBAP / TID Checks (TCP only)
    if raw_frame and len(raw_frame) >= 6:
        # MBAP Header: TID(2), PID(2), Len(2)
        try:
            tid, pid, length = struct.unpack(">HHH", raw_frame[:6])

            if sent_tid is not None and tid != sent_tid:
                violations.append(
                    f"VIOLATION: Transaction ID Mismatch. Sent {sent_tid}, received {tid}."
                )

            # MBAP Length check: Does it match the remaining bytes?
            # MBAP Length field includes Unit ID (1) + PDU (Function Code (1) + Data (N))
            remaining_bytes = len(raw_frame) - 6
            if length != remaining_bytes:
                violations.append(
                    f"VIOLATION: MBAP Length Mismatch. Header says {length} bytes follow, "
                    f"but {remaining_bytes} bytes were received."
                )
        except (struct.error, IndexError):
            violations.append("VIOLATION: Malformed MBAP header.")

    # 4. Gap Check
    gap_warn = check_gaps(pdu_data[1:])
    if gap_warn:
        violations.append(gap_warn)

    return violations




def decode_packet_string(data: bytes) -> str:
    """
    Decode a raw Modbus packet into a human-readable string.
    Always includes the raw hex at the end for safety.
    """
    raw_hex = data.hex().upper()
    try:
        # PDU Handling logic
        # We need to guess if it's TCP or RTU to find PDU start.
        
        fc = 0
        pdu = b''
        header_summary = ""
        
        # Try TCP (Header 7 bytes usually: TID(2) PID(2) LEN(2) UID(1))
        # Valid Modbus TCP header has PID=0
        # Also check if declared Length matches actual data length
        is_tcp = False
        if len(data) > 7 and data[2] == 0 and data[3] == 0:
            declared_len = struct.unpack(">H", data[4:6])[0]
            if len(data) - 6 == declared_len:
                is_tcp = True

        if is_tcp:
             # Decode MBAP
             tid, pid, length, uid = struct.unpack(">HHHB", data[:7])
             pdu = data[7:]
             header_summary = f"[TCP TID={tid} UID={uid}] "
        
        # Try RTU (Addr(1) PDU... CRC(2))
        elif len(data) > 3:
             # Basic length check passed. 
             # To be safer, we can check CRC if we want to be sure it's RTU.
             # However, logging might want to show "Bad CRC" packets too.
             # Let's check if it *looks* like a standard FC.
             
             uid = data[0]
             potential_fc = data[1]
             
             # If valid CRC, we definitely treat as RTU
             is_valid_crc = validate_rtu_crc(data)
             
             # If CRC invalid, but FC is standard, we might still want to decode 
             # but note the CRC error? Or just treat as Raw?
             # User asked "not data get lost". Raw hex is always at end.
             # Let's only decode structure if CRC is valid OR it looks very much like Modbus.
             
             if is_valid_crc:
                 pdu = data[1:-2]
                 header_summary = f"[RTU UID={uid}] "
             elif (
                 potential_fc in [3, 4, 6, 16] 
                 or (
                     (potential_fc & 0x80) 
                     and (potential_fc & 0x7F) in [3, 4, 6, 16]
                 )
             ):
                  # Looks like Modbus (valid FC) but bad CRC?
                  pdu = data[1:-2]
                  header_summary = f"[RTU(BadCRC) UID={uid}] "
        
        if not pdu:
            return f"Raw: {raw_hex}"
        fc = pdu[0]
        summary = f"FC{fc}"

        # READ HOLDING (03) / READ INPUT (04)
        if fc in [3, 4]: 
            fc_name = "ReadHolding" if fc == 3 else "ReadInput"
            # Request: [FC][AddrHi][AddrLo][CountHi][CountLo] (5 bytes)
            if len(pdu) == 5:
                addr = struct.unpack(">H", pdu[1:3])[0]
                count = struct.unpack(">H", pdu[3:5])[0]
                summary = f"{fc_name}(Addr={addr}, Cnt={count})"
            # Response: [FC][Bytes][Data...]
            elif len(pdu) >= 2:
                 byte_count = pdu[1]
                 # Peek at first register value if available
                 val_str = ""
                 if byte_count >= 2 and len(pdu) >= 4:
                     val = struct.unpack(">H", pdu[2:4])[0]
                     val_str = f", 1st={val}"
                 summary = f"{fc_name}Resp(Bytes={byte_count}{val_str})"

        # WRITE SINGLE REGISTER (06)
        elif fc == 6:
            # Request/Response: [FC][AddrHi][AddrLo][ValHi][ValLo] (5 bytes)
            if len(pdu) == 5:
                addr = struct.unpack(">H", pdu[1:3])[0]
                val = struct.unpack(">H", pdu[3:5])[0]
                summary = f"WriteSingle(Addr={addr}, Val={val})"

        # WRITE MULTIPLE REGISTERS (16 / 0x10)
        elif fc == 16:
             # Request: [FC][AddrHi][AddrLo][CountHi][CountLo][Bytes][Data...]
             if len(pdu) >= 6:
                 addr = struct.unpack(">H", pdu[1:3])[0]
                 count = struct.unpack(">H", pdu[3:5])[0]
                 byte_count = pdu[5]
                 summary = f"WriteMultiple(Addr={addr}, Cnt={count}, Bytes={byte_count})"
             # Response: [FC][AddrHi][AddrLo][CountHi][CountLo]
             elif len(pdu) == 5:
                 addr = struct.unpack(">H", pdu[1:3])[0]
                 count = struct.unpack(">H", pdu[3:5])[0]
                 summary = f"WriteMultipleResp(Addr={addr}, Cnt={count})"

        elif fc & 0x80: # Exception
             if len(pdu) >= 2:
                 code = pdu[1]
                 summary = f"Exception(Code={code})"

        return f"{header_summary}{summary} [{raw_hex}]"

    except Exception:
        # Fallback to raw hex if decoding fails
        return f"Raw(DecodeErr): {raw_hex}"
