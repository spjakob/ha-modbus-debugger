import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from custom_components.ha_modbus_debugger.modbus import ModbusHub
from custom_components.ha_modbus_debugger.const import (
    CONF_CONNECTION_TYPE,
    CONF_PORT,
    CONF_BAUDRATE,
    CONF_PARITY,
    CONF_STOPBITS,
    CONF_BYTESIZE,
    CONNECTION_TYPE_SERIAL,
    CONF_TIMEOUT,
    CONF_HOST,
    CONNECTION_TYPE_TCP,
)
from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusException

@pytest.mark.asyncio
async def test_serial_initialization():
    """Test that serial client is initialized with correct parameters."""
    config = {
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_SERIAL,
        CONF_PORT: "/dev/ttyUSB0",
        CONF_BAUDRATE: 9600,
        CONF_PARITY: "N",
        CONF_STOPBITS: 1,
        CONF_BYTESIZE: 8,
        CONF_TIMEOUT: 2,
    }

    hub = ModbusHub(config)

    # Patch the class where it is USED (in modbus.py)
    with patch("custom_components.ha_modbus_debugger.modbus.AsyncModbusSerialClient") as mock_cls:
        mock_instance = mock_cls.return_value
        mock_instance.connect = AsyncMock()
        mock_instance.connected = True

        success = await hub.connect()
        assert success is True

        # Verify constructor arguments
        mock_cls.assert_called_once()
        call_args = mock_cls.call_args

        # Port can be positional or keyword
        port_arg = call_args.kwargs.get("port")
        if port_arg is None and len(call_args.args) > 0:
            port_arg = call_args.args[0]

        assert port_arg == "/dev/ttyUSB0"
        assert call_args.kwargs.get("baudrate") == 9600
        assert call_args.kwargs.get("parity") == "N"
        assert call_args.kwargs.get("stopbits") == 1
        assert call_args.kwargs.get("bytesize") == 8
        assert call_args.kwargs.get("timeout") == 2

@pytest.mark.asyncio
async def test_connection_failure_handling():
    """Test that connection failures are caught and handled."""
    config = {
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP,
        CONF_HOST: "127.0.0.1",
        CONF_PORT: 502,
        CONF_TIMEOUT: 1
    }

    hub = ModbusHub(config)

    # Simulate a connection exception
    with patch("pymodbus.client.AsyncModbusTcpClient.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = ConnectionException("Connection Refused")

        success = await hub.connect()

        assert success is False
        assert "Connection Refused" in str(hub.last_error)
        assert hub._client is None  # Should be cleared to force recreation

@pytest.mark.asyncio
async def test_read_input_registers():
    """Test that input registers are read correctly."""
    config = {
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP,
        CONF_HOST: "127.0.0.1",
        CONF_PORT: 502,
    }

    hub = ModbusHub(config)

    # Mock the client instance
    hub._client = MagicMock(spec=AsyncModbusTcpClient)
    hub._client.connected = True
    hub._client.read_input_registers = AsyncMock()

    # Mock successful response
    mock_res = MagicMock()
    mock_res.isError.return_value = False
    mock_res.registers = [123]
    hub._client.read_input_registers.return_value = mock_res

    result = await hub.read_input_registers(slave=1, address=10, count=1)

    assert result == mock_res
    hub._client.read_input_registers.assert_called_with(10, count=1, slave=1)

@pytest.mark.asyncio
async def test_pymodbus_version_keyword_handling():
    """Test compatibility with different keyword args (slave vs device_id)."""
    config = {
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP,
        CONF_HOST: "127.0.0.1",
        CONF_PORT: 502,
    }
    hub = ModbusHub(config)
    hub._client = MagicMock(spec=AsyncModbusTcpClient)
    hub._client.connected = True

    # Case 1: Client accepts 'slave' (Older v3 or specific versions)
    hub._client.read_holding_registers = AsyncMock()

    await hub.read_holding_registers(slave=1, address=10, count=1)
    hub._client.read_holding_registers.assert_called_with(10, count=1, slave=1)

    # Case 2: Client raises TypeError for 'slave' and needs 'device_id' (Newer v3)
    hub._client.read_holding_registers.reset_mock()

    async def side_effect(*args, **kwargs):
        if 'slave' in kwargs:
            raise TypeError("unexpected keyword argument 'slave'")
        return MagicMock()

    hub._client.read_holding_registers.side_effect = side_effect

    await hub.read_holding_registers(slave=1, address=10, count=1)

    # We expect it to have been called twice: once with slave (failed), once with device_id
    assert hub._client.read_holding_registers.call_count == 2
    call_args = hub._client.read_holding_registers.call_args_list
    assert 'slave' in call_args[0].kwargs
    assert 'device_id' in call_args[1].kwargs
