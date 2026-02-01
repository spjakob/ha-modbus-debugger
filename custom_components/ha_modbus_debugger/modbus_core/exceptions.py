"""Modbus Debugger Exceptions."""

class ModbusError(Exception):
    """Base class for Modbus exceptions."""
    pass

class ModbusConnectionError(ModbusError):
    """Raised when connection fails."""
    pass

class ModbusTimeoutError(ModbusError):
    """Raised when request times out."""
    pass

class ModbusInvalidResponseError(ModbusError):
    """Raised when response is invalid (CRC, length, etc)."""
    pass

class ModbusExceptionResponseError(ModbusError):
    """Raised when device returns a Modbus Exception code."""
    def __init__(self, code, message="Modbus Exception"):
        self.code = code
        self.message = message
        super().__init__(f"{message}: Code {code}")
