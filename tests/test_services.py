import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.ha_modbus_debugger.actions import (
    SERVICE_READ_REGISTER,
    register_services,
)
from custom_components.ha_modbus_debugger.const import DOMAIN


async def async_test_read_register_service():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.services.async_register = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    await register_services(hass)
    handler = next(
        call[0][2]
        for call in hass.services.async_register.call_args_list
        if call[0][1] == SERVICE_READ_REGISTER
    )
    entry_data = {
        "name": "Test Hub",
        "host": "127.0.0.1",
        "port": 502,
        "connection_type": "tcp",
    }
    hass.config_entries.async_get_entry.return_value = MagicMock(data=entry_data)
    call = MagicMock()
    call.data = {"hub_id": "h", "unit_id": 1, "register": 10, "count": 1}
    with patch("custom_components.ha_modbus_debugger.actions.read.get_client") as MC:
        MC.return_value.execute.return_value = bytes.fromhex("021234")
        response = await handler(call)
        assert response["table"][0]["uint16"] == 0x1234


def test_read_register_service():
    asyncio.run(async_test_read_register_service())
