import unittest
import struct
from custom_components.ha_modbus_debugger.modbus_core.protocol import (
    compute_crc,
    build_rtu_request,
    build_tcp_request,
    validate_rtu_crc,
    parse_response_pdu,
)


class TestModbusProtocol(unittest.TestCase):
    def test_compute_crc(self):
        payload = bytes.fromhex("010300000001")
        self.assertEqual(compute_crc(payload), 0x0A84)

    def test_build_rtu_request(self):
        data = struct.pack(">HH", 0, 1)
        self.assertEqual(
            build_rtu_request(1, 3, data), bytes.fromhex("010300000001840A")
        )

    def test_build_tcp_request(self):
        data = struct.pack(">HH", 0, 1)
        self.assertEqual(
            build_tcp_request(5, 1, 3, data), bytes.fromhex("000500000006010300000001")
        )

    def test_validate_rtu_crc(self):
        self.assertTrue(validate_rtu_crc(bytes.fromhex("01030204D23AD9")))

    def test_parse_response_pdu_success(self):
        fc, data = parse_response_pdu(bytes.fromhex("030204D2"))
        self.assertEqual(fc, 3)
        self.assertEqual(data, bytes.fromhex("0204D2"))
