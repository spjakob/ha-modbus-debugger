"""Modbus Protocol Handling."""

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
