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
                # IMPORTANT: We return the actual ID we found so caller can detect mismatch
                return {"error": f"Unit ID mismatch", "found_id": resp_unit_id, "expected_id": unit_id}

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
                return {"error": f"Unit ID mismatch", "found_id": resp_unit_id, "expected_id": unit_id}

            pdu_data = payload_without_crc[1:]

        if not pdu_data:
             return {"error": "Empty PDU"}

        func_code = pdu_data[0]

        if func_code >= 0x80:
            exception_code = pdu_data[1] if len(pdu_data) > 1 else 0
            return {
                "error": "Modbus Exception",
                "exception_code": exception_code,
                "raw": response_data.hex(),
                "unit_id": unit_id # Confirmed ID
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

    def _read_exactly_sync(self, sock, n, timeout, start_time_ref=None):
        """Read exactly n bytes from socket (Sync)."""
        data = b''
        # If start_time_ref is provided, use it to calculate remaining timeout
        # Otherwise start new timer
        start_time = start_time_ref if start_time_ref else time.perf_counter()

        sock.settimeout(timeout) # Initial safe timeout, but we adjust manually in loop if needed

        while len(data) < n:
            remaining = n - len(data)
            elapsed = time.perf_counter() - start_time
            if elapsed >= timeout:
                raise socket.timeout

            sock.settimeout(max(0.01, timeout - elapsed))

            try:
                chunk = sock.recv(remaining)
                if not chunk:
                    raise EOFError("Connection closed")
                data += chunk
            except socket.timeout:
                raise
        return data

    def _read_packet_tcp_sync(self, sock, unit_id, timeout):
        """Read a full TCP Modbus packet."""
        start_time = time.perf_counter()

        if not self.rtu_over_tcp:
            # Header: 7 bytes
            header = self._read_exactly_sync(sock, 7, timeout, start_time)
            length_field = struct.unpack('>H', header[4:6])[0]
            remaining = length_field - 1 # UnitID is in header[6] (already read), length includes it

            if remaining > 0:
                pdu = self._read_exactly_sync(sock, remaining, timeout, start_time)
                return header + pdu
            return header
        else:
            # RTU over TCP
            # Read Unit(1) + Func(1)
            header = self._read_exactly_sync(sock, 2, timeout, start_time)
            func_code = header[1]

            expected_remaining = 0
            if func_code >= 0x80:
                expected_remaining = 3 # Code(1) + CRC(2)
            else:
                # We don't know count yet. We need to read ByteCount(1)
                byte_count_b = self._read_exactly_sync(sock, 1, timeout, start_time)
                byte_count = byte_count_b[0]
                header += byte_count_b
                expected_remaining = byte_count + 2 # Data + CRC

            rest = self._read_exactly_sync(sock, expected_remaining, timeout, start_time)
            return header + rest

    def _read_packet_serial_sync(self, ser, timeout):
        """Read a full RTU packet from serial."""
        start_time = time.perf_counter()

        # Check timeout for read loop
        def check_timeout():
            if (time.perf_counter() - start_time) > timeout:
                raise socket.timeout("Serial Timeout")

        # Read Header: Unit(1) + Func(1)
        header = b''
        while len(header) < 2:
            check_timeout()
            remaining_time = max(0.01, timeout - (time.perf_counter() - start_time))
            ser.timeout = remaining_time
            chunk = ser.read(2 - len(header))
            if not chunk:
                # If we timeout here, it's just no data
                raise socket.timeout("Serial Timeout")
            header += chunk

        func = header[1]
        remaining = 0

        if func >= 0x80:
            remaining = 3 # Code(1) + CRC(2)
        else:
            # Read Byte Count
            byte_count_b = b''
            while len(byte_count_b) < 1:
                check_timeout()
                remaining_time = max(0.01, timeout - (time.perf_counter() - start_time))
                ser.timeout = remaining_time
                chunk = ser.read(1)
                if not chunk: raise socket.timeout
                byte_count_b += chunk

            header += byte_count_b
            byte_count = byte_count_b[0]
            remaining = byte_count + 2 # Data + CRC

        rest = b''
        while len(rest) < remaining:
            check_timeout()
            remaining_time = max(0.01, timeout - (time.perf_counter() - start_time))
            ser.timeout = remaining_time
            chunk = ser.read(remaining - len(rest))
            if not chunk: raise socket.timeout
            rest += chunk

        return header + rest

    def _perform_request_with_match(self, send_func, read_func, unit_id, register, count, reg_type, timeout, log_func):
        """
        Send Request and Read Response with 'Read-Until-Match' logic.
        send_func: callable() -> None (sends the packet)
        read_func: callable(timeout) -> bytes (reads a full packet)
        """
        # Send
        send_func()

        start_time = time.perf_counter()

        while True:
            elapsed = time.perf_counter() - start_time
            remaining = timeout - elapsed
            if remaining <= 0:
                raise socket.timeout("Timeout waiting for match")

            try:
                response = read_func(remaining)
            except (socket.timeout, EOFError):
                raise

            # Parse to check ID
            # We pass empty request_packet because we don't use it for simple parsing
            parsed = self._parse_response_packet(b'', response, unit_id)

            if "error" in parsed and "Unit ID mismatch" in parsed.get("error", ""):
                found = parsed.get("found_id")
                log_func(f"WARNING: Ghost data: Unit {found} response received while scanning Unit {unit_id}. Discarding.")
                continue # Loop again

            # Match or other error
            return response, parsed

    def scan_tcp(self, start_unit: int, end_unit: int, register: int, reg_type: int,
                       timeout: float, retries: int, update_callback=None, log_callback=None) -> List[Dict]:
        """Run a TCP Scan (Sync/Blocking) with Read-Until-Match."""
        results = []

        def _log(msg):
             if log_callback: log_callback(msg)

        sock = None
        try:
            _log(f"Connecting to {self.host}:{self.port}...")
            try:
                sock = socket.create_connection((self.host, self.port), timeout=timeout)
                _log("Connected.")
            except Exception as e:
                _log(f"Connection Failed: {e}")
                return [{"error": str(e)}]

            for unit_id in range(start_unit, end_unit + 1):
                success = False
                for attempt in range(retries + 1):
                    req_start_time = time.perf_counter()
                    try:
                        if sock is None:
                            try:
                                sock = socket.create_connection((self.host, self.port), timeout=timeout)
                            except Exception as e:
                                _log(f"Unit {unit_id}: Connection Failed - {e}")
                                break

                        # Check for Ghost Data (Pre-send drain)
                        r, _, _ = select.select([sock], [], [], 0)
                        if r:
                            ghost = sock.recv(1024)
                            _log(f"Unit {unit_id}: WARNING - Ghost data cleared before sending: {ghost.hex()}")

                        # Prepare Send/Read functions
                        def send_tcp():
                            _log(f"DEBUG: Sending request to Unit {unit_id}...")
                            req = self._build_request_packet(unit_id, reg_type, register, 1, transaction_id=unit_id)
                            sock.sendall(req)

                        def read_tcp(t):
                            return self._read_packet_tcp_sync(sock, unit_id, t)

                        # Execute Read-Until-Match
                        response, parsed = self._perform_request_with_match(
                            send_tcp, read_tcp, unit_id, register, 1, reg_type, timeout, _log
                        )

                        elapsed = time.perf_counter() - req_start_time

                        if "registers" in parsed and parsed["registers"]:
                            val = parsed["registers"][0]
                            _log(f"INFO: Unit {unit_id}: Found ({elapsed:.2f}s) - Data: 0x{val:04X}")
                            res = {
                                "unit_id": unit_id,
                                "register": register,
                                "value": val,
                                "hex": f"0x{val:04X}"
                            }
                            results.append(res)
                            if update_callback: update_callback(res)
                            success = True
                            break
                        elif "exception_code" in parsed:
                            _log(f"INFO: Unit {unit_id}: Exception ({elapsed:.2f}s) - Code {parsed['exception_code']}")
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
                        elif "error" in parsed:
                             _log(f"DEBUG: Unit {unit_id}: Error ({elapsed:.2f}s) - {parsed['error']}")
                             continue

                    except (OSError, socket.timeout, EOFError) as e:
                        elapsed = time.perf_counter() - req_start_time
                        err_str = "Error"
                        if isinstance(e, socket.timeout):
                            err_str = "Timeout"
                        else:
                            if sock: sock.close()
                            sock = None

                        # Only log final failure if out of retries, or log every attempt as debug
                        _log(f"DEBUG: Unit {unit_id}: {err_str} ({elapsed:.2f}s)")
                        continue

        finally:
            if sock:
                sock.close()
            _log("INFO: Scan complete. Connection closed.")

        return results

    def scan_serial(self, start_unit: int, end_unit: int, register: int, reg_type: int,
                    timeout: float, retries: int, update_callback=None, log_callback=None) -> List[Dict]:
        """Run a Serial Scan (Blocking/Sync) with Read-Until-Match."""
        results = []

        def _log(msg):
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
            _log(f"Failed to open port: {e}")
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
                            _log(f"Unit {unit_id}: WARNING - Ghost data cleared before sending: {ghost.hex()}")

                        def send_serial():
                            _log(f"DEBUG: Sending request to Unit {unit_id}...")
                            req = self._build_request_packet(unit_id, reg_type, register, 1)
                            ser.write(req)
                            ser.flush()

                        def read_serial(t):
                            return self._read_packet_serial_sync(ser, t)

                        response, parsed = self._perform_request_with_match(
                            send_serial, read_serial, unit_id, register, 1, reg_type, timeout, _log
                        )

                        elapsed = time.perf_counter() - req_start_time

                        if "registers" in parsed and parsed["registers"]:
                            val = parsed["registers"][0]
                            _log(f"INFO: Unit {unit_id}: Found ({elapsed:.2f}s) - Data: 0x{val:04X}")
                            res = {
                                "unit_id": unit_id,
                                "register": register,
                                "value": val,
                                "hex": f"0x{val:04X}"
                            }
                            results.append(res)
                            if update_callback: update_callback(res)
                            success = True
                            break
                        elif "exception_code" in parsed:
                            _log(f"INFO: Unit {unit_id}: Exception ({elapsed:.2f}s) - Code {parsed['exception_code']}")
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
                        elif "error" in parsed:
                             _log(f"DEBUG: Unit {unit_id}: Error ({elapsed:.2f}s) - {parsed['error']}")
                             ser.reset_input_buffer()
                             continue

                    except Exception as e:
                        elapsed = time.perf_counter() - req_start_time
                        err_str = "Error"
                        if "Timeout" in str(e):
                             err_str = "Timeout"
                        _log(f"DEBUG: Unit {unit_id}: {err_str} ({elapsed:.2f}s)")
                        ser.reset_input_buffer()
                        continue

        finally:
            if ser and ser.is_open:
                ser.close()
            _log("INFO: Scan complete. Connection closed.")

        return results

    # Re-implement read_registers_tcp/serial using the new helpers?
    # For now, I will leave them as single-shot unless user complains about Ghost Data on read_registers too.
    # But to be safe, I should update them to use _read_packet_tcp_sync structure at least.
    # The current read_registers implementation uses _perform_tcp_request_sync which I removed/refactored.
    # Wait, I removed `_perform_tcp_request_sync` in the code above? No, I deleted it.
    # So `read_registers_tcp` will break if I don't update it.

    # Let's fix read_registers_tcp to use `_perform_request_with_match` as well (robustness).

    def read_registers_tcp(self, unit_id: int, register: int, count: int, reg_type: int,
                          timeout: float, retries: int, log_callback=None) -> Dict[str, Any]:
        """Read registers via TCP (Sync)."""

        MAX_COUNT = 125
        if count <= MAX_COUNT:
            return self._read_block_tcp(unit_id, register, count, reg_type, timeout, retries, log_callback)
        else:
            combined_registers = []
            current_reg = register
            remaining = count

            while remaining > 0:
                chunk_size = min(remaining, MAX_COUNT)
                res = self._read_block_tcp(unit_id, current_reg, chunk_size, reg_type, timeout, retries, log_callback)
                if "error" in res: return res
                if "registers" in res: combined_registers.extend(res["registers"])
                current_reg += chunk_size
                remaining -= chunk_size

            return {"registers": combined_registers, "unit_id": unit_id}

    def _read_block_tcp(self, unit_id, register, count, reg_type, timeout, retries, log_callback):
        sock = None
        last_error = "Unknown Error"
        def _log(msg):
             if log_callback: log_callback(msg)

        try:
            sock = socket.create_connection((self.host, self.port), timeout=timeout)

            for attempt in range(retries + 1):
                try:
                    # Drain
                    r, _, _ = select.select([sock], [], [], 0)
                    if r: sock.recv(1024)

                    def send_func():
                        req = self._build_request_packet(unit_id, reg_type, register, count, transaction_id=unit_id)
                        sock.sendall(req)

                    def read_func(t):
                        # _read_packet_tcp_sync handles single register or block?
                        # It reads header then PDU based on length. PDU length depends on byte count in response.
                        # The logic in _read_packet_tcp_sync is generic for TCP (reads length from header).
                        # For RTU over TCP, it needs to know structure?
                        # My _read_packet_tcp_sync for RTU over TCP was hardcoded for 1 register response size?
                        # Let's check _read_packet_tcp_sync.
                        return self._read_packet_tcp_sync(sock, unit_id, t)

                    # Wait, _read_packet_tcp_sync logic for RTU over TCP:
                    # "expected_remaining = byte_count + 2". It reads byte_count from the stream.
                    # So it supports variable length. Good.

                    response, parsed = self._perform_request_with_match(
                        send_func, read_func, unit_id, register, count, reg_type, timeout, _log
                    )
                    return parsed

                except Exception as e:
                    last_error = str(e)
                    if sock: sock.close()
                    sock = socket.create_connection((self.host, self.port), timeout=timeout)
                    continue
        except Exception as e:
            return {"error": str(e)}
        finally:
            if sock: sock.close()
        return {"error": last_error}

    def read_registers_serial(self, unit_id: int, register: int, count: int, reg_type: int,
                              timeout: float, retries: int, log_callback=None) -> Dict[str, Any]:
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
                if "error" in res: return res
                if "registers" in res: combined_registers.extend(res["registers"])
                current_reg += chunk_size
                remaining -= chunk_size
            return {"registers": combined_registers, "unit_id": unit_id}

    def _read_block_serial(self, unit_id, register, count, reg_type, timeout, retries, log_callback):
        def _log(msg):
             if log_callback: log_callback(msg)
        try:
            ser = serial.Serial(port=self.port, baudrate=self.baudrate, parity=self.parity, stopbits=self.stopbits, bytesize=self.bytesize, timeout=timeout)
        except Exception as e:
            return {"error": f"Failed to open port: {e}"}

        last_error = "Unknown Error"
        try:
            for attempt in range(retries + 1):
                try:
                    ser.reset_input_buffer()
                    def send_func():
                        req = self._build_request_packet(unit_id, reg_type, register, count)
                        ser.write(req)
                        ser.flush()

                    def read_func(t):
                        return self._read_packet_serial_sync(ser, t)

                    response, parsed = self._perform_request_with_match(
                        send_func, read_func, unit_id, register, count, reg_type, timeout, _log
                    )
                    return parsed
                except Exception as e:
                    last_error = str(e)
                    continue
        finally:
            if ser.is_open: ser.close()
        return {"error": last_error}
