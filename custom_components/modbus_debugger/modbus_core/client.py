"""Synchronous Modbus Client."""

import socket
import time
import logging
import serial

from .protocol import (
    build_tcp_request,
    build_rtu_request,
    parse_mbap_header,
    validate_rtu_crc,
    parse_response_pdu,
)
from .exceptions import (
    ModbusConnectionError,
    ModbusTimeoutError,
    ModbusInvalidResponseError,
    ModbusError,
)

_LOGGER = logging.getLogger(__name__)


class LateResponse:
    """Represents a response that arrived late (matching a previous request)."""

    def __init__(self, unit_id, function_code, data):
        self.unit_id = unit_id
        self.function_code = function_code
        self.data = data


class SyncModbusClient:
    """Synchronous Modbus Client handling TCP, RTU, and RTU-over-TCP."""

    def __init__(
        self,
        connection_type: str,
        host: str = None,
        port: int = 502,
        timeout: float = 2.0,
        retries: int = 0,
        # Serial params
        baudrate: int = 9600,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: int = 1,
        # RTU over TCP
        rtu_over_tcp: bool = False,
    ):
        self.connection_type = connection_type
        self.host = host
        self.port = port
        self.timeout = timeout
        self.retries = retries

        # Serial configuration
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits

        self.rtu_over_tcp = rtu_over_tcp

        self._socket = None
        self._serial = None
        self._transaction_id = 0
        self._last_error = None
        self._late_responses = []  # Buffer for late responses found during execution

        # Callback for detailed packet logging (injected by services)
        self.trace_callback = None

    def connect(self):
        """Establish connection."""
        self.close()  # Ensure clean slate

        try:
            if self.connection_type == "tcp":
                self._socket = socket.create_connection(
                    (self.host, self.port), timeout=self.timeout
                )
            elif self.connection_type == "serial":
                self._serial = serial.Serial(
                    port=self.host,  # Config flow passes port as host usually, or we map it
                    baudrate=self.baudrate,
                    bytesize=self.bytesize,
                    parity=self.parity,
                    stopbits=self.stopbits,
                    timeout=self.timeout,
                )
            if self.trace_callback:
                self.trace_callback(f"Connected to {self.host}:{self.port}")
        except Exception as e:
            _LOGGER.error("Connection failed: %s", e)
            if self.trace_callback:
                self.trace_callback(f"Connection failed: {e}")
            raise ModbusConnectionError(f"Failed to connect: {e}")

    def close(self):
        """Close connection."""
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

    def execute(
        self, unit_id: int, function_code: int, data: bytes
    ) -> bytes | LateResponse:
        """Execute a Modbus Request with Smart Drain and Late Recovery."""
        if not self._socket and not self._serial:
            self.connect()

        self._transaction_id = (self._transaction_id + 1) & 0xFFFF

        # 1. Smart Drain: Clear ghost data
        drained_bytes = self._drain_input()
        if drained_bytes:
            msg = f"Smart Drain (Ghost Data): {drained_bytes.hex().upper()}"
            _LOGGER.debug(msg)
            if self.trace_callback:
                self.trace_callback(msg)

        # 2. Build Request
        if self.connection_type == "tcp" and not self.rtu_over_tcp:
            req = build_tcp_request(self._transaction_id, unit_id, function_code, data)
        else:
            # Serial or RTU-over-TCP
            req = build_rtu_request(unit_id, function_code, data)

        # 3. Send
        if self.trace_callback:
            self.trace_callback(f"TX: {req.hex().upper()}")

        start_time = time.monotonic()
        try:
            if self._socket:
                self._socket.sendall(req)
            elif self._serial:
                self._serial.write(req)
        except Exception as e:
            _LOGGER.error("Send failed: %s", e)
            self.close()
            raise ModbusConnectionError(f"Send failed: {e}")

        # 4. Read Loop (Late Recovery)
        # We loop until we get a response for OUR unit_id, or timeout.
        # If we get a response for another unit_id, we store it and keep waiting.

        while (time.monotonic() - start_time) < self.timeout:
            remaining_time = self.timeout - (time.monotonic() - start_time)
            if remaining_time <= 0:
                break

            try:
                if self.connection_type == "tcp" and not self.rtu_over_tcp:
                    resp_unit, resp_fc, resp_data, raw_frame = self._read_packet_tcp(
                        remaining_time
                    )
                else:
                    resp_unit, resp_fc, resp_data, raw_frame = self._read_packet_rtu(
                        remaining_time
                    )

                if self.trace_callback:
                    self.trace_callback(f"RX: {raw_frame.hex().upper()}")

                # Check match
                if resp_unit == unit_id:
                    # Verify FC if needed (optional, but good practice)
                    # Note: Error responses have MSB set
                    if (resp_fc & 0x7F) == (function_code & 0x7F):
                        return resp_data
                    else:
                        _LOGGER.warning(
                            "Function code mismatch: sent %s, got %s",
                            function_code,
                            resp_fc,
                        )
                        # Could be a weird error or another device. Treat as ghost?
                        # For now, let's assume it's valid data for this unit.
                        return resp_data  # Protocol parser handles exception codes

                # Mismatch - Late Response?
                msg = f"Ghost Data Detected: Expected ID {unit_id}, got ID {resp_unit}"
                _LOGGER.warning(msg)
                if self.trace_callback:
                    self.trace_callback(msg)

                self._late_responses.append(LateResponse(resp_unit, resp_fc, resp_data))
                # Continue loop...

            except (ModbusTimeoutError, TimeoutError, socket.timeout):
                # Actual timeout on the socket read
                break
            except ModbusError as e:
                # CRC error etc
                _LOGGER.warning("Modbus Error during read loop: %s", e)
                if self.trace_callback:
                    self.trace_callback(f"Read Error: {e}")
                # If it's a CRC error or similar, we might want to keep listening?
                # For safety, let's break to avoid infinite loops on noise.
                break
            except Exception as e:
                _LOGGER.error("Unexpected error during read: %s", e)
                self.close()
                raise ModbusConnectionError(f"Read failed: {e}")

        raise ModbusTimeoutError(
            f"No response from Unit {unit_id} within {self.timeout}s"
        )

    def _drain_input(self) -> bytes:
        """Read all available data from input buffer."""
        data = b""
        try:
            if self._socket:
                # Set non-blocking
                self._socket.setblocking(False)
                try:
                    while True:
                        chunk = self._socket.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                except BlockingIOError:
                    pass  # No more data
                finally:
                    self._socket.setblocking(True)
            elif self._serial:
                if self._serial.in_waiting > 0:
                    data = self._serial.read(self._serial.in_waiting)
        except Exception as e:
            _LOGGER.warning("Error draining input buffer: %s", e)
        return data

    def _read_packet_tcp(self, timeout: float) -> tuple[int, int, bytes, bytes]:
        """Read a full Modbus TCP packet."""
        self._socket.settimeout(timeout)

        # 1. Read MBAP (6 bytes) to get length
        # TID (2), PID (2), Len (2)
        mbap = self._recv_n(6)
        tid, pid, length = parse_mbap_header(mbap)

        # 2. Read Body (Length bytes)
        # Body starts with Unit ID (1 byte), then PDU
        if length < 1:
            raise ModbusInvalidResponseError("Invalid packet length")

        body = self._recv_n(length)
        unit_id = body[0]
        pdu = body[1:]

        fc, data = parse_response_pdu(pdu)
        return unit_id, fc, data, (mbap + body)

    def _read_packet_rtu(self, timeout: float) -> tuple[int, int, bytes, bytes]:
        """Read a full Modbus RTU packet."""
        # RTU does not have a length header. We must read until silence or valid frame?
        # Implementing robust RTU reading over stream is hard without silence detection.
        # But we know structure: Addr (1), FC (1), Data (N), CRC (2).
        # Data length depends on FC.
        # For FC03 response: Bytes (1), Data (N), CRC(2).
        # For Exception: Code (1), CRC(2).

        # Approach: Read header (2 bytes: Addr, FC). Determine remaining length?
        # This is tricky because "Byte Count" is inside data for some FCs.

        if self._socket:
            self._socket.settimeout(timeout)
            reader = self._socket.recv
        else:
            self._serial.timeout = timeout
            reader = self._serial.read

        # 1. Read Address (1 byte)
        addr_byte = self._recv_rtu_n(1, reader)
        unit_id = addr_byte[0]

        # 2. Read FC (1 byte)
        fc_byte = self._recv_rtu_n(1, reader)
        fc = fc_byte[0]

        # 3. Determine remaining length
        # Response to Read Holding (03) / Input (04): [BytesCount] [Data...] [CRC] [CRC]
        # Response to Write Single (06): [Addr] [Addr] [Val] [Val] [CRC] [CRC] -> Fixed 4 bytes data + 2 crc
        # Exception: [ErrCode] [CRC] [CRC]

        remaining = b""

        if fc & 0x80:
            # Exception: 1 byte code + 2 crc
            remaining = self._recv_rtu_n(3, reader)
        elif fc in [0x01, 0x02, 0x03, 0x04]:
            # Read functions: Next byte is byte count
            count_byte = self._recv_rtu_n(1, reader)
            count = count_byte[0]
            remaining = count_byte + self._recv_rtu_n(count + 2, reader)  # Data + CRC
        elif fc in [0x05, 0x06, 0x0F, 0x10]:
            # Write functions returns fixed echo usually?
            # 05/06: 4 bytes data + 2 crc
            # 15/16: 4 bytes data + 2 crc
            remaining = self._recv_rtu_n(6, reader)
        else:
            # Unknown FC, naive read?
            # For debugger, we mostly care about 03.
            # If we don't support it, we might get stuck.
            raise ModbusInvalidResponseError(
                f"Unsupported Function Code in response: {fc}"
            )

        full_frame = addr_byte + fc_byte + remaining

        # Verify CRC
        if not validate_rtu_crc(full_frame):
            raise ModbusInvalidResponseError("CRC Mismatch")

        # Parse PDU (Strip CRC)
        pdu = full_frame[1:-2]  # Skip Unit, drop CRC
        fc_out, data_out = parse_response_pdu(pdu)
        return unit_id, fc_out, data_out, full_frame

    def _recv_n(self, n: int) -> bytes:
        """Helper to recv exactly n bytes from TCP socket."""
        data = b""
        while len(data) < n:
            chunk = self._socket.recv(n - len(data))
            if not chunk:
                raise ModbusConnectionError("Connection closed by peer")
            data += chunk
        return data

    def _recv_rtu_n(self, n: int, reader_func) -> bytes:
        """Helper to recv exactly n bytes for RTU."""
        # For serial, reader_func(n) handles timeout return short.
        # For socket (RTU over TCP), recv(n) might return short?
        # Actually socket.recv() returns what is available.

        if self._socket:
            # Emulate read(n) behavior
            data = b""
            # We rely on socket timeout set in _read_packet_rtu
            while len(data) < n:
                chunk = reader_func(n - len(data))
                if not chunk:
                    raise ModbusConnectionError("Connection closed")
                data += chunk
            return data
        else:
            # Serial read
            data = reader_func(n)
            if len(data) < n:
                raise ModbusTimeoutError("Incomplete read")
            return data
