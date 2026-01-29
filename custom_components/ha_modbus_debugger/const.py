"""Constants for the Modbus Debugger integration."""

DOMAIN = "ha_modbus_debugger"
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

CONNECTION_TYPE_TCP = "tcp"
CONNECTION_TYPE_SERIAL = "serial"

DEFAULT_PORT = 502
DEFAULT_BAUDRATE = 9600
DEFAULT_BYTESIZE = 8
DEFAULT_PARITY = "N"
DEFAULT_STOPBITS = 1
DEFAULT_TIMEOUT = 3

# For Options Flow (Sensors)
CONF_UNIT_ID = "unit_id"
CONF_REGISTER = "register"
CONF_COUNT = "count"
CONF_DATA_TYPE = "data_type"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_SENSORS = "sensors"

DATA_TYPE_INT16 = "int16"
DATA_TYPE_UINT16 = "uint16"
DATA_TYPE_INT32 = "int32"
DATA_TYPE_UINT32 = "uint32"
DATA_TYPE_FLOAT16 = "float16"
DATA_TYPE_FLOAT32 = "float32"
DATA_TYPE_STRING = "string"
