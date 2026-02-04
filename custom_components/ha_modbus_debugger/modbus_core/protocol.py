import struct
from .exceptions import ModbusInvalidResponseError, ModbusExceptionResponseError
def compute_crc(data: bytes) -> int:
    crc = 0xFFFF
    for char in data:
        crc ^= char
        for _ in range(8):
            if crc & 0x0001:
                crc >>= 1; crc ^= 0xA001
            else: crc >>= 1
    return crc
def build_rtu_request(unit_id: int, function_code: int, data: bytes) -> bytes:
    packet = struct.pack(">B", unit_id) + struct.pack(">B", function_code) + data
    crc = compute_crc(packet)
    return packet + struct.pack("<H", crc)
def build_tcp_request(transaction_id: int, unit_id: int, function_code: int, data: bytes) -> bytes:
    length = 1 + 1 + len(data)
    header = struct.pack(">HHH", transaction_id, 0, length)
    body = struct.pack(">BB", unit_id, function_code) + data
    return header + body
def parse_mbap_header(header_data: bytes) -> tuple[int, int, int]:
    if len(header_data) == 6:
        return struct.unpack(">HHH", header_data)
    if len(header_data) == 7:
        tid, pid, length, uid = struct.unpack(">HHHB", header_data)
        return tid, pid, length
    raise ModbusInvalidResponseError(f"MBAP header must be 6 or 7 bytes, got {len(header_data)}")
def validate_rtu_crc(data: bytes) -> bool:
    if len(data) < 4: return False
    return struct.unpack("<H", data[-2:])[0] == compute_crc(data[:-2])
def parse_response_pdu(data: bytes) -> tuple[int, bytes]:
    if len(data) < 2: raise ModbusInvalidResponseError("Response too short")
    fc = data[0]
    if fc & 0x80: raise ModbusExceptionResponseError(data[1])
    return fc, data[1:]
