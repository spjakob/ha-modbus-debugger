
import asyncio
import unittest
from unittest.mock import MagicMock, patch
import struct
import sys
import os

# Mock Home Assistant modules BEFORE importing local modules
sys.modules['homeassistant'] = MagicMock()
sys.modules['homeassistant.core'] = MagicMock()
sys.modules['homeassistant.exceptions'] = MagicMock()
sys.modules['homeassistant.config_entries'] = MagicMock()
sys.modules['homeassistant.const'] = MagicMock()
sys.modules['homeassistant.helpers'] = MagicMock()
sys.modules['homeassistant.helpers.device_registry'] = MagicMock()

# Add repo root to path to import local modules
sys.path.append(os.getcwd())

# Now we can import safely (hopefully)
# But wait, scanner imports .const.
# custom_components/ha_modbus_debugger/__init__.py might still be loaded if we import from the package.
# To bypass __init__.py issues, we can import scanner directly if we manipulate path differently,
# or just rely on the mocks. Since we mocked homeassistant.*, __init__.py should execute fine (it just imports them).

from custom_components.ha_modbus_debugger.scanner import ModbusScanner
from custom_components.ha_modbus_debugger.const import (
    CONNECTION_TYPE_SERIAL,
    CONNECTION_TYPE_TCP,
    CONF_HOST,
    CONF_PORT,
    CONF_CONNECTION_TYPE,
    CONF_RTU_OVER_TCP
)

class TestModbusScanner(unittest.TestCase):
    def setUp(self):
        self.tcp_config = {
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP,
            CONF_HOST: "127.0.0.1",
            CONF_PORT: 502
        }
        self.serial_config = {
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_SERIAL,
            CONF_PORT: "/dev/ttyUSB0",
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_SERIAL # Fix key
        }

    def test_crc(self):
        scanner = ModbusScanner(self.serial_config)
        # Test CRC for standard query: Unit 1, Read Holding 0, 1 reg
        # Request: 01 03 00 00 00 01
        # CRC Should be: 84 0A (Low High) -> 0x0A84
        payload = bytes.fromhex("010300000001")
        crc = scanner._calculate_crc(payload)
        self.assertEqual(crc, bytes.fromhex("840A"))

    def test_build_packet_tcp(self):
        scanner = ModbusScanner(self.tcp_config)
        # Unit 1, Func 3, Start 0, Count 1, TID 5
        pkt = scanner._build_request_packet(1, 3, 0, 1, transaction_id=5)
        # MBAP: 00 05 00 00 00 06 (Len=6: Unit 1 + PDU 5)
        # Unit: 01
        # PDU: 03 00 00 00 01
        expected = bytes.fromhex("000500000006010300000001")
        self.assertEqual(pkt, expected)

    def test_build_packet_rtu(self):
        scanner = ModbusScanner(self.serial_config)
        pkt = scanner._build_request_packet(1, 3, 0, 1)
        # 01 03 00 00 00 01 + CRC
        expected = bytes.fromhex("010300000001840A")
        self.assertEqual(pkt, expected)

    def test_parse_response_tcp_success(self):
        scanner = ModbusScanner(self.tcp_config)
        # Unit 1, Func 3, Bytes 2, Val 1234 (0x04D2)
        # MBAP: 00 00 00 00 00 05
        # Unit: 01
        # PDU: 03 02 04 D2
        response = bytes.fromhex("00000000000501030204D2")
        parsed = scanner._parse_response_packet(b'', response, unit_id=1)
        self.assertEqual(parsed["registers"][0], 0x04D2)

    def test_parse_response_tcp_error(self):
        scanner = ModbusScanner(self.tcp_config)
        # Error: Unit 1, Func 0x83, Code 02
        # MBAP: ... 00 03
        # Unit: 01
        # PDU: 83 02
        response = bytes.fromhex("000000000003018302")
        parsed = scanner._parse_response_packet(b'', response, unit_id=1)
        self.assertIn("exception_code", parsed)
        self.assertEqual(parsed["exception_code"], 2)

    def test_parse_response_rtu_success(self):
        scanner = ModbusScanner(self.serial_config)
        # Unit 1, Func 3, Bytes 2, Val 0x04D2 + CRC
        # CRC of 01 03 02 04 D2 is D9 3A -> Packed 3A D9
        response = bytes.fromhex("01030204D23AD9")
        parsed = scanner._parse_response_packet(b'', response, unit_id=1)
        self.assertEqual(parsed["registers"][0], 0x04D2)

    def test_parse_response_rtu_crc_error(self):
        scanner = ModbusScanner(self.serial_config)
        # Bad CRC
        response = bytes.fromhex("01030204D2FFFF")
        parsed = scanner._parse_response_packet(b'', response, unit_id=1)
        self.assertEqual(parsed["error"], "CRC Error")

if __name__ == '__main__':
    unittest.main()
