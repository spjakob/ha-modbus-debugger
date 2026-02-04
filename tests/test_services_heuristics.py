
import pytest, asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from custom_components.ha_modbus_debugger.actions import *
from custom_components.ha_modbus_debugger.const import DOMAIN
async def async_test_scan_devices_heuristics():
    hass = MagicMock()
    entry = MagicMock()
    entry.data = {"name": "Test Hub", "host": "127.0.0.1", "port": 4196, "connection_type": "tcp"}
    hass.config_entries.async_get_entry.return_value = entry
    hass.async_add_executor_job = AsyncMock(side_effect=lambda f, *a: f(*a))
    await register_services(hass)
    handler = next(c[0][2] for c in hass.services.async_register.call_args_list if c[0][1] == SERVICE_SCAN_DEVICES)
    call = MagicMock(data={"hub_id": "test", "start_unit": 1, "end_unit": 2, "register": 0, "register_type": "holding", "timeout": 1.0, "verbosity": "debug"})
    with patch("custom_components.ha_modbus_debugger.actions.scan.SyncModbusClient") as MockClient:
        MockClient.return_value.execute.side_effect = Exception("Timeout")
        response = await handler(call)
        assert any("Using non-standard port 4196" in t for t in response.get("trace", []))
def test_scan_devices_heuristics():
    asyncio.run(async_test_scan_devices_heuristics())
