import sys
from unittest.mock import MagicMock

# Mock homeassistant and other dependencies
sys.modules["homeassistant"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.config_entries"] = MagicMock()
sys.modules["homeassistant.exceptions"] = MagicMock()
sys.modules["serial"] = MagicMock()

import unittest
import struct
from custom_components.modbus_debugger.modbus_core.protocol import validate_response

class TestValidationLogic(unittest.TestCase):
    def test_validation_success(self):
        # FC 03, Byte Count 2, Data [00 01]
        pdu_data = bytes.fromhex("020001")
        violations = validate_response(pdu_data, expected_count=1)
        self.assertEqual(violations, [])

    def test_byte_count_mismatch(self):
        # Expected 1 reg (2 bytes), device says 4 bytes
        pdu_data = bytes.fromhex("0400010002")
        violations = validate_response(pdu_data, expected_count=1)
        self.assertTrue(any("VIOLATION: Byte Count Mismatch" in v for v in violations))

    def test_payload_mismatch(self):
        # Claimed 4 bytes, actual 2 bytes
        pdu_data = bytes.fromhex("040001")
        violations = validate_response(pdu_data, expected_count=2)
        # It will have byte count match (4 == 2*2), but payload mismatch (2 != 4)
        self.assertTrue(any("VIOLATION: Payload Mismatch" in v for v in violations))

    def test_tid_mismatch(self):
        pdu_data = bytes.fromhex("020001")
        # TCP Header: TID=5, PID=0, Len=4 (UID=1, FC=3, Data=2)
        raw_frame = bytes.fromhex("0005000000040103020001")
        violations = validate_response(pdu_data, expected_count=1, sent_tid=6, raw_frame=raw_frame)
        self.assertTrue(any("VIOLATION: Transaction ID Mismatch" in v for v in violations))

    def test_mbap_length_mismatch(self):
        pdu_data = bytes.fromhex("020001")
        # TCP Header: TID=5, PID=0, Len=10 (but only 5 follow)
        raw_frame = bytes.fromhex("00050000000A0103020001")
        violations = validate_response(pdu_data, expected_count=1, sent_tid=5, raw_frame=raw_frame)
        self.assertTrue(any("VIOLATION: MBAP Length Mismatch" in v for v in violations))

    def test_gap_detection(self):
        # 11 zeros
        pdu_data = bytes.fromhex("0C") + b"\x00" * 11
        violations = validate_response(pdu_data, expected_count=6)
        self.assertTrue(any("WARNING: Large block of zeros/ones detected" in v for v in violations))

if __name__ == "__main__":
    unittest.main()
