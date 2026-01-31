import asyncio
import logging
import socket
import struct
import time
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

    async def _read_exactly(self, reader, n, timeout):
        """Read exactly n bytes from reader."""
        data = b''
        start_time = time.perf_counter()
        while len(data) < n:
            remaining = n - len(data)
            elapsed = time.perf_counter() - start_time
            if elapsed >= timeout:
                raise asyncio.TimeoutError

            chunk = await asyncio.wait_for(reader.read(remaining), timeout=timeout - elapsed)
            if not chunk:
                raise EOFError("Connection closed")
            data += chunk
        return data

    async def _perform_tcp_request(self, reader, writer, unit_id, register, reg_type, timeout):
        """Send request and read response using open connection."""
        req = self._build_request_packet(unit_id, reg_type, register, 1, transaction_id=unit_id)
        writer.write(req)
        await writer.drain()

        if not self.rtu_over_tcp:
            # Modbus TCP Header: 7 bytes
            header = await self._read_exactly(reader, 7, timeout)
            # header[4:6] is length field
            length_field = struct.unpack('>H', header[4:6])[0]
            # Length includes UnitID (1 byte) which is in header[6]
            remaining = length_field - 1
            if remaining > 0:
                pdu = await self._read_exactly(reader, remaining, timeout)
                return header + pdu
            return header

        else:
            # RTU over TCP
            # Read Unit(1) + Func(1)
            header = await self._read_exactly(reader, 2, timeout)
            func_code = header[1]

            expected_remaining = 0
            if func_code >= 0x80:
                # Error: Code(1) + CRC(2) = 3 bytes
                expected_remaining = 3
            else:
                # Success (Read 1 reg): Bytes(1) + Data(2) + CRC(2) = 5 bytes
                expected_remaining = 5

            rest = await self._read_exactly(reader, expected_remaining, timeout)
            return header + rest

    async def scan_tcp(self, start_unit: int, end_unit: int, register: int, reg_type: int,
                       timeout: float, retries: int, concurrency: int,
                       update_callback=None, log_callback=None) -> List[Dict]:
        """Run a TCP Scan (Async)."""
        results = []

        def _log_debug(msg):
             if log_callback: log_callback(msg)

        # Persistent Scan (Sequential) if concurrency == 1
        if concurrency == 1:
            reader, writer = None, None
            try:
                for unit_id in range(start_unit, end_unit + 1):
                    success = False
                    for attempt in range(retries + 1):
                        try:
                            # Connect if needed
                            if writer is None or writer.is_closing():
                                _log_debug(f"Connecting to {self.host}:{self.port}...")
                                try:
                                    reader, writer = await asyncio.wait_for(
                                        asyncio.open_connection(self.host, self.port),
                                        timeout=timeout
                                    )
                                    _log_debug("Connected.")
                                except (OSError, asyncio.TimeoutError) as e:
                                    # Enhance error logging for connection failures
                                    err_msg = str(e)
                                    if isinstance(e, asyncio.TimeoutError):
                                        err_msg = "Connection Timeout"
                                    elif isinstance(e, ConnectionRefusedError):
                                        err_msg = "Connection Refused"
                                    elif isinstance(e, socket.gaierror):
                                        err_msg = "Host Name Resolution Failed"
                                    elif isinstance(e, OSError) and e.errno == 113: # No route to host
                                        err_msg = "No Route to Host"

                                    _log_debug(f"Failed to connect to {self.host}:{self.port} - {err_msg}")
                                    writer = None
                                    reader = None
                                    raise e

                            _log_debug(f"Sending request to Unit {unit_id} (Attempt {attempt+1}/{retries+1})")
                            response = await self._perform_tcp_request(reader, writer, unit_id, register, reg_type, timeout)
                            _log_debug(f"Received response from Unit {unit_id}: {response.hex()}")

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
                            elif "registers" in parsed and not parsed["registers"]:
                                # Empty registers?
                                res = {
                                    "unit_id": unit_id,
                                    "register": register,
                                    "value": None,
                                    "error": "Empty Response"
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
                            elif "error" in parsed:
                                # Logic to retry if parsing error (e.g. CRC/length)
                                _log_debug(f"Parsing Error Unit {unit_id}: {parsed['error']}")
                                continue

                        except (OSError, asyncio.TimeoutError, EOFError) as e:
                            if writer:
                                writer.close()
                                try:
                                    await writer.wait_closed()
                                except: pass
                                writer = None
                                reader = None
                            continue

                    if not success:
                         _log_debug(f"Unit {unit_id}: No Response")

            finally:
                if writer:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except: pass

            return results

        # Concurrent Scan (Connection Per Request)
        semaphore = asyncio.Semaphore(concurrency)

        async def scan_one(unit_id):
            async with semaphore:
                for attempt in range(retries + 1):
                    try:
                        _log_debug(f"Connecting to {self.host}:{self.port} (Unit {unit_id})...")
                        reader, writer = None, None
                        try:
                            reader, writer = await asyncio.wait_for(
                                asyncio.open_connection(self.host, self.port),
                                timeout=timeout
                            )
                        except (OSError, asyncio.TimeoutError) as e:
                            err_msg = str(e)
                            if isinstance(e, asyncio.TimeoutError):
                                err_msg = "Connection Timeout"
                            elif isinstance(e, ConnectionRefusedError):
                                err_msg = "Connection Refused"
                            elif isinstance(e, socket.gaierror):
                                err_msg = "Host Name Resolution Failed"
                            elif isinstance(e, OSError) and e.errno == 113:
                                err_msg = "No Route to Host"

                            _log_debug(f"Unit {unit_id}: Connection Failed - {err_msg}")
                            continue

                        try:
                            _log_debug(f"Sending request to Unit {unit_id} (Attempt {attempt+1}/{retries+1})")
                            response = await self._perform_tcp_request(reader, writer, unit_id, register, reg_type, timeout)
                            _log_debug(f"Received response from Unit {unit_id}: {response.hex()}")

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
                                return
                            elif "registers" in parsed and not parsed["registers"]:
                                res = {
                                    "unit_id": unit_id,
                                    "register": register,
                                    "value": None,
                                    "error": "Empty Response"
                                }
                                results.append(res)
                                if update_callback: update_callback(res)
                                return
                            elif "exception_code" in parsed:
                                res = {
                                    "unit_id": unit_id,
                                    "register": register,
                                    "value": None,
                                    "error": f"Exception Code {parsed['exception_code']}"
                                }
                                results.append(res)
                                if update_callback: update_callback(res)
                                return
                        finally:
                            writer.close()
                            await writer.wait_closed()

                    except (OSError, asyncio.TimeoutError, EOFError) as e:
                        _log_debug(f"Unit {unit_id}: Error - {e}")
                        continue

                _log_debug(f"Unit {unit_id}: No Response")

        tasks = [scan_one(u) for u in range(start_unit, end_unit + 1)]
        await asyncio.gather(*tasks)
        return results

    def scan_serial(self, start_unit: int, end_unit: int, register: int, reg_type: int,
                    timeout: float, retries: int, update_callback=None, log_callback=None) -> List[Dict]:
        """Run a Serial Scan (Blocking/Sync)."""
        results = []

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
            _LOGGER.error(f"Failed to open serial port: {e}")
            _log_debug(f"Failed to open serial port: {e}")
            return [{"error": f"Failed to open port: {e}"}]

        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            for unit_id in range(start_unit, end_unit + 1):
                success = False
                for attempt in range(retries + 1):
                    try:
                        _log_debug(f"Sending request to Unit {unit_id} (Attempt {attempt+1}/{retries+1})")
                        req = self._build_request_packet(unit_id, reg_type, register, 1)
                        ser.write(req)
                        ser.flush()

                        # RTU Response (1 reg): 7 bytes
                        # RTU Error: 5 bytes
                        response = ser.read(5)
                        if len(response) < 5:
                            _log_debug(f"Unit {unit_id}: Incomplete response (Header)")
                            continue

                        func = response[1]
                        if func < 0x80:
                            # Expect 2 more bytes (CRC)
                            rest = ser.read(2)
                            response += rest

                        if len(response) < 5:
                            continue

                        _log_debug(f"Received response from Unit {unit_id}: {response.hex()}")

                        parsed = self._parse_response_packet(req, response, unit_id)
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
                        elif "registers" in parsed and not parsed["registers"]:
                            res = {
                                "unit_id": unit_id,
                                "register": register,
                                "value": None,
                                "error": "Empty Response"
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
                    except Exception as e:
                        _log_debug(f"Serial scan error unit {unit_id}: {e}")
                        ser.reset_input_buffer()
                        continue

                if not success:
                     _log_debug(f"Unit {unit_id}: No Response")

        finally:
            if ser.is_open:
                ser.close()

        return results
