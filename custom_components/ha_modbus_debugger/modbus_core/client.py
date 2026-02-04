import socket, struct, time, logging, serial
from .protocol import build_tcp_request, build_rtu_request, parse_mbap_header, validate_rtu_crc, parse_response_pdu
from .exceptions import ModbusConnectionError, ModbusTimeoutError, ModbusInvalidResponseError, ModbusExceptionResponseError, ModbusError

_LOGGER = logging.getLogger(__name__)

class LateResponse:
    def __init__(self, unit_id, function_code, data):
        self.unit_id = unit_id
        self.function_code = function_code
        self.data = data

class SyncModbusClient:
    def __init__(self, connection_type, host=None, port=502, timeout=2.0, retries=0, baudrate=9600, bytesize=8, parity='N', stopbits=1, rtu_over_tcp=False):
        self.connection_type = connection_type
        self.host = host
        self.port = port
        self.timeout = timeout
        self.retries = retries
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.rtu_over_tcp = rtu_over_tcp
        self._socket = None
        self._serial = None
        self._transaction_id = 0
        self._late_responses = []

    def connect(self):
        self.close()
        try:
            if self.connection_type == "tcp":
                self._socket = socket.create_connection((self.host, self.port), timeout=self.timeout)
            elif self.connection_type == "serial":
                self._serial = serial.Serial(port=self.host, baudrate=self.baudrate, bytesize=self.bytesize, parity=self.parity, stopbits=self.stopbits, timeout=self.timeout)
        except Exception as e:
            raise ModbusConnectionError(f"Failed to connect: {e}")

    def close(self):
        if self._socket: self._socket.close(); self._socket = None
        if self._serial: self._serial.close(); self._serial = None

    def execute(self, unit_id, function_code, data):
        if not self._socket and not self._serial: self.connect()
        self._transaction_id = (self._transaction_id + 1) & 0xFFFF
        self._drain_input()

        req = build_tcp_request(self._transaction_id, unit_id, function_code, data) if (self.connection_type == "tcp" and not self.rtu_over_tcp) else build_rtu_request(unit_id, function_code, data)

        try:
            if self._socket: self._socket.sendall(req)
            elif self._serial: self._serial.write(req)
        except Exception as e:
            self.close(); raise ModbusConnectionError(f"Send failed: {e}")

        start_time = time.monotonic()
        while (time.monotonic() - start_time) < self.timeout:
            remaining = self.timeout - (time.monotonic() - start_time)
            if remaining <= 0: break
            try:
                if self.connection_type == "tcp" and not self.rtu_over_tcp:
                    resp_unit, resp_fc, resp_data = self._read_packet_tcp(remaining)
                else:
                    resp_unit, resp_fc, resp_data = self._read_packet_rtu(remaining)

                if resp_unit == unit_id: return resp_data
                self._late_responses.append(LateResponse(resp_unit, resp_fc, resp_data))
            except ModbusTimeoutError: break
            except Exception: break
        raise ModbusTimeoutError(f"Timeout Unit {unit_id}")

    def _drain_input(self):
        try:
            if self._socket:
                self._socket.setblocking(False)
                while self._socket.recv(4096): pass
            elif self._serial:
                if self._serial.in_waiting > 0: self._serial.read(self._serial.in_waiting)
        except: pass
        finally:
            if self._socket: self._socket.setblocking(True)

    def _read_packet_tcp(self, timeout):
        self._socket.settimeout(timeout)
        mbap = self._recv_n(6)
        tid, pid, length = struct.unpack(">HHH", mbap)
        body = self._recv_n(length)
        return body[0], body[1], body[2:]

    def _read_packet_rtu(self, timeout):
        if self._socket: self._socket.settimeout(timeout); reader = self._socket.recv
        else: self._serial.timeout = timeout; reader = self._serial.read

        addr = self._recv_rtu_n(1, reader)[0]
        fc = self._recv_rtu_n(1, reader)[0]

        if fc & 0x80: rem = self._recv_rtu_n(3, reader)
        elif fc in [1, 2, 3, 4]:
            cnt = self._recv_rtu_n(1, reader)[0]
            rem = bytes([cnt]) + self._recv_rtu_n(cnt + 2, reader)
        else: rem = self._recv_rtu_n(6, reader)

        full = bytes([addr, fc]) + rem
        if not validate_rtu_crc(full): raise ModbusInvalidResponseError("CRC")
        return addr, fc, full[2:-2]

    def _recv_n(self, n):
        data = b""
        while len(data) < n:
            chunk = self._socket.recv(n - len(data))
            if not chunk: raise ModbusConnectionError("Closed")
            data += chunk
        return data

    def _recv_rtu_n(self, n, reader):
        if self._socket:
            data = b""
            while len(data) < n:
                chunk = reader(n - len(data))
                if not chunk: raise ModbusConnectionError("Closed")
                data += chunk
            return data
        else:
            data = reader(n)
            if len(data) < n: raise ModbusTimeoutError("Short")
            return data
