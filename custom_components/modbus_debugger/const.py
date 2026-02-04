"""Constants for the Modbus Debugger integration."""

DOMAIN = "modbus_debugger"
CONF_CONNECTION_TYPE = "connection_type"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_RTU_OVER_TCP = "rtu_over_tcp"
CONF_BAUDRATE = "baudrate"
CONF_PARITY = "parity"
CONF_STOPBITS = "stopbits"
CONF_BYTESIZE = "bytesize"
CONF_METHOD = "method"
CONF_TIMEOUT = "timeout"
CONF_NAME = "name"
CONF_IS_DEFAULT = "is_default"

CONNECTION_TYPE_TCP = "tcp"
CONNECTION_TYPE_SERIAL = "serial"

DEFAULT_PORT = 502
DEFAULT_BAUDRATE = 9600
DEFAULT_BYTESIZE = 8
DEFAULT_PARITY = "N"
DEFAULT_STOPBITS = 1
DEFAULT_TIMEOUT = 3
