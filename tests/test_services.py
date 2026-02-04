
import pytest, asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from custom_components.ha_modbus_debugger.actions import *
from custom_components.ha_modbus_debugger.const import DOMAIN
async def async_test_read_register_service():
    hass = MagicMock()
    entry = MagicMock()
    entry.data = {"name": "Test Hub", "host": "127.0.0.1", "port": 502, "connection_type": "tcp"}
    hass.config_entries.async_get_entry.return_value = entry
    hass.async_add_executor_job = AsyncMock(side_effect=lambda f, *a: f(*a))
    await register_services(hass)
    handler = next(c[0][2] for c in hass.services.async_register.call_args_list if c[0][1] == SERVICE_READ_REGISTER)
    call = MagicMock(data={"hub_id": "test", "unit_id": 1, "register": 10, "count": 1, "register_type": "holding"})
    with patch("custom_components.ha_modbus_debugger.actions.read.SyncModbusClient") as MockClient:
        MockClient.return_value.execute.return_value = bytes.fromhex("021234")
        response = await handler(call)
        assert response["table"][0]["uint16"] == 0x1234
def test_read_register_service():
    asyncio.run(async_test_read_register_service())
