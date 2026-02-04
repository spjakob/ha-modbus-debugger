class ModbusError(Exception):
    """Base class for modbus errors."""

class ModbusConnectionError(ModbusError):
    """Error connecting to gateway."""

class ModbusTimeoutError(ModbusError):
    """Timeout waiting for response."""

class ModbusInvalidResponseError(ModbusError):
    """Response packet is invalid or corrupted."""

class ModbusExceptionResponseError(ModbusError):
    """Gateway returned a Modbus Exception (e.g. 0x02 Illegal Address)."""
    def __init__(self, code):
        self.code = code
        super().__init__(f"Modbus Exception Code {code}")
