
import unittest, struct
from custom_components.ha_modbus_debugger.modbus_core.protocol import *
from custom_components.ha_modbus_debugger.modbus_core.exceptions import *
class TestModbusProtocol(unittest.TestCase):
    def test_compute_crc(self):
        self.assertEqual(compute_crc(bytes.fromhex("010300000001")), 0x0A84)
    def test_build_tcp_request(self):
        self.assertEqual(build_tcp_request(5, 1, 3, bytes.fromhex("00000001")), bytes.fromhex("000500000006010300000001"))
    def test_parse_mbap_header(self):
        self.assertEqual(parse_mbap_header(bytes.fromhex("000500000006")), (5, 0, 6))
    def test_parse_response_pdu(self):
        self.assertEqual(parse_response_pdu(bytes.fromhex("03021234")), (3, bytes.fromhex("021234")))
if __name__ == '__main__': unittest.main()
