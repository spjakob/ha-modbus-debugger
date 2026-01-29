import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from custom_components.ha_modbus_debugger.modbus import ModbusHub
from custom_components.ha_modbus_debugger.const import (
    CONF_CONNECTION_TYPE, CONF_HOST, CONF_PORT, CONNECTION_TYPE_TCP, CONF_RTU_OVER_TCP
)

@pytest.mark.asyncio
async def test_connect_tcp():
    config = {
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP,
        CONF_HOST: "127.0.0.1",
        CONF_PORT: 502,
        CONF_RTU_OVER_TCP: False
    }

    with patch("custom_components.ha_modbus_debugger.modbus.AsyncModbusTcpClient") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.connect = AsyncMock()
        mock_client.connected = True

        hub = ModbusHub(config)
        assert await hub.connect() is True
        mock_client.connect.assert_called_once()

@pytest.mark.asyncio
async def test_read_holding_registers():
    config = {
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP,
        CONF_HOST: "127.0.0.1",
        CONF_PORT: 502,
    }

    with patch("custom_components.ha_modbus_debugger.modbus.AsyncModbusTcpClient") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.connect = AsyncMock()
        mock_client.connected = True
        mock_client.read_holding_registers = AsyncMock()

        # Mock Response
        mock_response = MagicMock()
        mock_response.registers = [123]
        mock_response.isError.return_value = False
        mock_client.read_holding_registers.return_value = mock_response

        hub = ModbusHub(config)
        await hub.connect()

        result = await hub.read_holding_registers(1, 0, 1)
        assert result == mock_response
        assert result.registers == [123]

@pytest.mark.asyncio
async def test_stats():
    config = {
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP,
        CONF_HOST: "127.0.0.1",
        CONF_PORT: 502,
    }

    hub = ModbusHub(config)
    hub.report_stat(1, success=True)
    hub.report_stat(1, success=False)
    hub.report_stat(1, success=True)

    stats = hub.get_stats(1)
    assert stats["success"] == 2
    assert stats["fail"] == 1

    stats_2 = hub.get_stats(2)
    assert stats_2["success"] == 0
