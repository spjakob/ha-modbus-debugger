import logging
import socket
import struct
import time
import select
from typing import Any, Dict, List, Optional

import serial

from .const import (
    CONNECTION_TYPE_SERIAL,
    CONNECTION_TYPE_TCP,
    CONF_HOST,
    CONF_PORT,
    CONF_BAUDRATE,
    CONF_PARITY,
    CONF_STOPBITS,
    CONF_BYTESIZE,
    CONF_RTU_OVER_TCP,
)

_LOGGER = logging.getLogger(__name__)

# Modbus Function Codes
READ_HOLDING_REGISTERS = 0x03
READ_INPUT_REGISTERS = 0x04

class ModbusScanner:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.connection_type = config.get("connection_type")
        self.rtu_over_tcp = config.get(CONF_RTU_OVER_TCP, False)

        # Serial settings
        self.port = config.get(CONF_PORT)
        self.baudrate = config.get(CONF_BAUDRATE, 9600)
        self.parity = config.get(CONF_PARITY, "N")
        self.stopbits = config.get(CONF_STOPBITS, 1)
        self.bytesize = config.get(CONF_BYTESIZE, 8)

        # TCP settings
        self.host = config.get(CONF_HOST)
        # Port is same key

    def _calculate_crc(self, data: bytes) -> bytes:
        """Calculate CRC16 (Modbus)."""
        crc = 0xFFFF
        for char in data:
            crc ^= char
            for _ in range(8):
                if (crc & 0x0001):
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return struct.pack('<H', crc)

    def _build_request_packet(self, unit_id: int, func_code: int, start_address: int, count: int, transaction_id: int = 0) -> bytes:
        """Build the Modbus request packet."""
        pdu = struct.pack('>BHH', func_code, start_address, count)

        if self.connection_type == CONNECTION_TYPE_TCP and not self.rtu_over_tcp:
            length = 1 + len(pdu)
            mbap = struct.pack('>HHH', transaction_id, 0, length)
            return mbap + struct.pack('>B', unit_id) + pdu
        else:
            payload = struct.pack('>B', unit_id) + pdu
            crc = self._calculate_crc(payload)
            return payload + crc

    def _parse_response_packet(self, request_packet: bytes, response_data: bytes, unit_id: int) -> Dict[str, Any]:
        """Parse the response packet."""
        if not response_data:
            return {"error": "No response"}

        pdu_data = response_data

        if self.connection_type == CONNECTION_TYPE_TCP and not self.rtu_over_tcp:
            if len(response_data) < 7:
                 return {"error": "Response too short (TCP Header)"}

            resp_unit_id = response_data[6]
            if resp_unit_id != unit_id:
                return {"error": f"Unit ID mismatch (Expected {unit_id}, got {resp_unit_id})"}

            pdu_data = response_data[7:]
        else:
            if len(response_data) < 4:
                return {"error": "Response too short (RTU)"}

            received_crc = response_data[-2:]
            payload_without_crc = response_data[:-2]
            calculated_crc = self._calculate_crc(payload_without_crc)

            if received_crc != calculated_crc:
                return {"error": "CRC Error"}

            resp_unit_id = payload_without_crc[0]
            if resp_unit_id != unit_id:
                return {"error": f"Unit ID mismatch (Expected {unit_id}, got {resp_unit_id})"}

            pdu_data = payload_without_crc[1:]

        if not pdu_data:
             return {"error": "Empty PDU"}

        func_code = pdu_data[0]

        if func_code >= 0x80:
            exception_code = pdu_data[1] if len(pdu_data) > 1 else 0
            return {
                "error": "Modbus Exception",
                "exception_code": exception_code,
                "raw": response_data.hex()
            }

        if len(pdu_data) < 2:
            return {"error": "PDU too short"}

        byte_count = pdu_data[1]
        data_bytes = pdu_data[2:]

        if len(data_bytes) != byte_count:
            return {"error": f"Byte count mismatch (Expected {byte_count}, got {len(data_bytes)})"}

        registers = []
        for i in range(0, len(data_bytes), 2):
            val = struct.unpack('>H', data_bytes[i:i+2])[0]
            registers.append(val)

        return {
            "registers": registers,
            "unit_id": unit_id
        }

    def _read_exactly_sync(self, sock, n, timeout):
        """Read exactly n bytes from socket (Sync)."""
        data = b''
        start_time = time.perf_counter()
        sock.settimeout(timeout)

        while len(data) < n:
            remaining = n - len(data)
            elapsed = time.perf_counter() - start_time
            if elapsed >= timeout:
                raise socket.timeout

            # Update timeout for remaining time
            sock.settimeout(max(0.01, timeout - elapsed))

            try:
                chunk = sock.recv(remaining)
                if not chunk:
                    raise EOFError("Connection closed")
                data += chunk
            except socket.timeout:
                raise
        return data

    def _perform_tcp_request_sync(self, sock, unit_id, register, count, reg_type, timeout):
        """Send request and read response using open socket."""
        req = self._build_request_packet(unit_id, reg_type, register, count, transaction_id=unit_id)
        sock.sendall(req)

        if not self.rtu_over_tcp:
            # Modbus TCP Header: 7 bytes
            header = self._read_exactly_sync(sock, 7, timeout)
            # header[4:6] is length field
            length_field = struct.unpack('>H', header[4:6])[0]
            # Length includes UnitID (1 byte) which is in header[6]
            remaining = length_field - 1
            if remaining > 0:
                pdu = self._read_exactly_sync(sock, remaining, timeout)
                return header + pdu
            return header

        else:
            # RTU over TCP
            # Read Unit(1) + Func(1)
            header = self._read_exactly_sync(sock, 2, timeout)
            func_code = header[1]

            expected_remaining = 0
            if func_code >= 0x80:
                # Error: Code(1) + CRC(2) = 3 bytes
                expected_remaining = 3
            else:
                # Success: Bytes(1) + Data(Count*2) + CRC(2)
                expected_remaining = 1 + (count * 2) + 2

            rest = self._read_exactly_sync(sock, expected_remaining, timeout)
            return header + rest

    def _perform_serial_request_sync(self, ser, unit_id, register, count, reg_type, timeout):
        """Send request and read response using open serial port."""
        req = self._build_request_packet(unit_id, reg_type, register, count)
        ser.write(req)
        ser.flush()

        # Initial read: Address(1) + Func(1) + Bytes(1) = 3 bytes min
        # Or Error: Address(1) + Func(1) + Code(1) + CRC(2) = 5 bytes

        # Let's try reading 3 bytes first to determine type
        # But wait, if it's error, the 3rd byte is Exception Code.
        # If success, 3rd byte is Byte Count.

        # Simplest: Read 2 bytes first (Addr + Func)
        header = ser.read(2)
        if len(header) < 2:
            return header # Timeout

        func = header[1]
        remaining = 0
        if func >= 0x80:
            # Exception: Code(1) + CRC(2)
            remaining = 3
        else:
            # Success: Bytes(1)
            # Read byte count to know rest
            byte_count_b = ser.read(1)
            if len(byte_count_b) < 1:
                return header + byte_count_b

            byte_count = byte_count_b[0]
            # Data(byte_count) + CRC(2)
            remaining = byte_count + 2
            header += byte_count_b

        rest = ser.read(remaining)
        return header + rest

    def read_registers_tcp(self, unit_id: int, register: int, count: int, reg_type: int,
                          timeout: float, retries: int, log_callback=None) -> Dict[str, Any]:
        """Read registers via TCP (Sync)."""
        MAX_COUNT = 125
        if count <= MAX_COUNT:
            # Single request
            return self._read_block_tcp(unit_id, register, count, reg_type, timeout, retries, log_callback)
        else:
            # Chunked
            combined_registers = []
            current_reg = register
            remaining = count

            while remaining > 0:
                chunk_size = min(remaining, MAX_COUNT)
                res = self._read_block_tcp(unit_id, current_reg, chunk_size, reg_type, timeout, retries, log_callback)

                if "error" in res:
                    return res # Return error immediately if chunk fails

                if "registers" in res:
                    combined_registers.extend(res["registers"])

                current_reg += chunk_size
                remaining -= chunk_size

            return {
                "registers": combined_registers,
                "unit_id": unit_id
            }

    def _read_block_tcp(self, unit_id, register, count, reg_type, timeout, retries, log_callback):
        sock = None
        last_error = "Unknown Error"

        def _log_debug(msg):
             if log_callback: log_callback(msg)

        try:
            # Connect once
            _log_debug(f"Connecting to {self.host}:{self.port}...")
            sock = socket.create_connection((self.host, self.port), timeout=timeout)
            _log_debug("Connected.")

            for attempt in range(retries + 1):
                try:
                    # Check for Ghost Data
                    r, _, _ = select.select([sock], [], [], 0)
                    if r:
                        ghost = sock.recv(1024)
                        _log_debug(f"Unit {unit_id}: WARNING - Ghost data cleared before sending: {ghost.hex()}")

                    req_start_time = time.perf_counter()
                    # _log_debug(f"Sending request: Unit {unit_id}, Addr {register}, Count {count}")
                    response = self._perform_tcp_request_sync(sock, unit_id, register, count, reg_type, timeout)
                    elapsed = time.perf_counter() - req_start_time
                    _log_debug(f"Unit {unit_id}: Response ({elapsed:.2f}s) Data: {response.hex()}")

                    parsed = self._parse_response_packet(b'', response, unit_id)
                    return parsed

                except (OSError, socket.timeout, EOFError) as e:
                    elapsed = time.perf_counter() - req_start_time
                    last_error = str(e)
                    err_str = "Error"
                    if isinstance(e, socket.timeout):
                         err_str = "Timeout"
                    _log_debug(f"Unit {unit_id}: {err_str} ({elapsed:.2f}s) - {e}")

                    # On fatal errors (not just timeout), maybe we should reconnect?
                    # For a single block read, if we fail, we fail. Retries handle it.
                    # If socket is broken, we must reconnect.
                    if not isinstance(e, socket.timeout):
                         if sock: sock.close()
                         sock = socket.create_connection((self.host, self.port), timeout=timeout)
                    continue
        except Exception as e:
             last_error = str(e)
             _log_debug(f"Connection Error: {e}")
        finally:
            if sock:
                sock.close()

        return {"error": last_error}


    def read_registers_serial(self, unit_id: int, register: int, count: int, reg_type: int,
                              timeout: float, retries: int, log_callback=None) -> Dict[str, Any]:
        """Read registers via Serial (Sync)."""
        MAX_COUNT = 125
        if count <= MAX_COUNT:
            return self._read_block_serial(unit_id, register, count, reg_type, timeout, retries, log_callback)
        else:
            combined_registers = []
            current_reg = register
            remaining = count

            while remaining > 0:
                chunk_size = min(remaining, MAX_COUNT)
                res = self._read_block_serial(unit_id, current_reg, chunk_size, reg_type, timeout, retries, log_callback)

                if "error" in res:
                    return res

                if "registers" in res:
                    combined_registers.extend(res["registers"])

                current_reg += chunk_size
                remaining -= chunk_size

            return {
                "registers": combined_registers,
                "unit_id": unit_id
            }

    def _read_block_serial(self, unit_id, register, count, reg_type, timeout, retries, log_callback):
        def _log_debug(msg):
             if log_callback: log_callback(msg)

        try:
            ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                parity=self.parity,
                stopbits=self.stopbits,
                bytesize=self.bytesize,
                timeout=timeout
            )
        except Exception as e:
            return {"error": f"Failed to open port: {e}"}

        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            last_error = "Unknown Error"

            for attempt in range(retries + 1):
                try:
                    # Check for Ghost Data
                    if ser.in_waiting > 0:
                        ghost = ser.read(ser.in_waiting)
                        _log_debug(f"Unit {unit_id}: WARNING - Ghost data cleared before sending: {ghost.hex()}")

                    req_start_time = time.perf_counter()
                    # _log_debug(f"Sending request: Unit {unit_id}, Addr {register}, Count {count}")
                    response = self._perform_serial_request_sync(ser, unit_id, register, count, reg_type, timeout)

                    elapsed = time.perf_counter() - req_start_time
                    if len(response) == 0:
                         _log_debug(f"Unit {unit_id}: Timeout ({elapsed:.2f}s)")
                         raise socket.timeout("Timeout") # Simulate timeout for retry logic

                    _log_debug(f"Unit {unit_id}: Response ({elapsed:.2f}s) Data: {response.hex()}")

                    parsed = self._parse_response_packet(b'', response, unit_id)
                    return parsed

                except Exception as e:
                    elapsed = time.perf_counter() - req_start_time
                    last_error = str(e)
                    err_str = "Error"
                    if "Timeout" in str(e): # Pyserial doesn't raise Timeout explicitly usually
                         err_str = "Timeout"
                    _log_debug(f"Unit {unit_id}: {err_str} ({elapsed:.2f}s) - {e}")

                    ser.reset_input_buffer()
                    continue

            return {"error": last_error}
        finally:
            if ser.is_open:
                ser.close()

    def scan_tcp(self, start_unit: int, end_unit: int, register: int, reg_type: int,
                       timeout: float, retries: int, update_callback=None, log_callback=None) -> List[Dict]:
        """Run a TCP Scan (Sync/Blocking) with Persistent Connection."""
        results = []

        def _log_debug(msg):
             if log_callback: log_callback(msg)

        sock = None
        try:
            _log_debug(f"Connecting to {self.host}:{self.port}...")
            try:
                sock = socket.create_connection((self.host, self.port), timeout=timeout)
                _log_debug("Connected.")
            except Exception as e:
                _log_debug(f"Connection Failed: {e}")
                return [{"error": str(e)}]

            for unit_id in range(start_unit, end_unit + 1):
                success = False
                for attempt in range(retries + 1):
                    req_start_time = time.perf_counter()
                    try:
                        # Reconnect if we lost it (e.g. fatal error previously)
                        if sock is None:
                            try:
                                sock = socket.create_connection((self.host, self.port), timeout=timeout)
                            except Exception as e:
                                _log_debug(f"Unit {unit_id}: Connection Failed - {e}")
                                break # Skip this unit

                        # Check for Ghost Data
                        r, _, _ = select.select([sock], [], [], 0)
                        if r:
                            ghost = sock.recv(1024)
                            _log_debug(f"Unit {unit_id}: WARNING - Ghost data cleared before sending: {ghost.hex()}")

                        response = self._perform_tcp_request_sync(sock, unit_id, register, 1, reg_type, timeout)
                        elapsed = time.perf_counter() - req_start_time
                        _log_debug(f"Unit {unit_id}: Response ({elapsed:.2f}s) Data: {response.hex()}")

                        parsed = self._parse_response_packet(b'', response, unit_id)

                        if "registers" in parsed and parsed["registers"]:
                            res = {
                                "unit_id": unit_id,
                                "register": register,
                                "value": parsed["registers"][0],
                                "hex": f"0x{parsed['registers'][0]:04X}"
                            }
                            results.append(res)
                            if update_callback: update_callback(res)
                            success = True
                            break
                        # ... other cases ...
                        elif "error" in parsed:
                             _log_debug(f"Parsing Error Unit {unit_id}: {parsed['error']}")
                             if "exception_code" in parsed:
                                 res = {
                                     "unit_id": unit_id,
                                     "register": register,
                                     "value": None,
                                     "error": f"Exception Code {parsed['exception_code']}"
                                 }
                                 results.append(res)
                                 if update_callback: update_callback(res)
                                 success = True
                                 break
                             continue

                    except (OSError, socket.timeout, EOFError) as e:
                        elapsed = time.perf_counter() - req_start_time

                        err_str = "Error"
                        if isinstance(e, socket.timeout):
                            err_str = "Timeout"
                            # Keep socket open on timeout
                        else:
                            # Fatal error, close and set to None to trigger reconnect next loop
                            if sock:
                                sock.close()
                                sock = None

                        if not success and attempt == retries:
                             _log_debug(f"Unit {unit_id}: {err_str} ({elapsed:.2f}s)")
                        else:
                             # Log retry if we are going to retry? Or just log error
                             # User said "Consolidate... combine them into one clear status"
                             # If we retry, maybe we shouldn't log every failure if it eventually succeeds?
                             # But this is a debugger. Logging every attempt is good.
                             _log_debug(f"Unit {unit_id}: {err_str} ({elapsed:.2f}s) - {e}")

                        continue

                # if not success:
                #      _log_debug(f"Unit {unit_id}: No Response")
                # Removed redundant log as requested ("Consolidate")

        finally:
            if sock:
                sock.close()

        return results

    def scan_serial(self, start_unit: int, end_unit: int, register: int, reg_type: int,
                    timeout: float, retries: int, update_callback=None, log_callback=None) -> List[Dict]:
        """Run a Serial Scan (Blocking/Sync) with Persistent Connection."""
        results = []

        def _log_debug(msg):
             if log_callback: log_callback(msg)

        ser = None
        try:
            ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                parity=self.parity,
                stopbits=self.stopbits,
                bytesize=self.bytesize,
                timeout=timeout
            )
        except Exception as e:
            _log_debug(f"Failed to open port: {e}")
            return [{"error": f"Failed to open port: {e}"}]

        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            for unit_id in range(start_unit, end_unit + 1):
                success = False
                for attempt in range(retries + 1):
                    req_start_time = time.perf_counter()
                    try:
                        # Check Ghost Data
                        if ser.in_waiting > 0:
                            ghost = ser.read(ser.in_waiting)
                            _log_debug(f"Unit {unit_id}: WARNING - Ghost data cleared before sending: {ghost.hex()}")

                        response = self._perform_serial_request_sync(ser, unit_id, register, 1, reg_type, timeout)

                        elapsed = time.perf_counter() - req_start_time

                        # Validate length roughly
                        if len(response) < 5:
                            _log_debug(f"Unit {unit_id}: Timeout ({elapsed:.2f}s)")
                            continue

                        _log_debug(f"Unit {unit_id}: Response ({elapsed:.2f}s) Data: {response.hex()}")

                        parsed = self._parse_response_packet(b'', response, unit_id)

                        if "registers" in parsed and parsed["registers"]:
                            res = {
                                "unit_id": unit_id,
                                "register": register,
                                "value": parsed["registers"][0],
                                "hex": f"0x{parsed['registers'][0]:04X}"
                            }
                            results.append(res)
                            if update_callback: update_callback(res)
                            success = True
                            break
                        elif "exception_code" in parsed:
                            res = {
                                "unit_id": unit_id,
                                "register": register,
                                "value": None,
                                "error": f"Exception Code {parsed['exception_code']}"
                            }
                            results.append(res)
                            if update_callback: update_callback(res)
                            success = True
                            break
                        # ...
                    except Exception as e:
                        elapsed = time.perf_counter() - req_start_time
                        _log_debug(f"Unit {unit_id}: Error ({elapsed:.2f}s) - {e}")
                        ser.reset_input_buffer()
                        continue

                # if not success:
                #      _log_debug(f"Unit {unit_id}: No Response") # Consolidated

        finally:
            if ser and ser.is_open:
                ser.close()

        return results
