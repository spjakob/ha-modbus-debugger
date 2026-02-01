import pytest
import logging
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from custom_components.ha_modbus_debugger.services import setup_services, SERVICE_READ_REGISTER, SERVICE_SCAN_DEVICES
from custom_components.ha_modbus_debugger.const import DOMAIN
from custom_components.ha_modbus_debugger.modbus import ModbusHub
from homeassistant.core import SupportsResponse

async def async_test_scan_devices_heuristics():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.services.async_register = MagicMock()
    hass.services.has_service.return_value = False

    async def mock_executor(func, *args):
        if asyncio.iscoroutinefunction(func):
             return await func(*args)
        result = func(*args)
        if asyncio.iscoroutine(result):
             return await result
        return result

    hass.async_add_executor_job = AsyncMock(side_effect=mock_executor)

    await setup_services(hass)

    handler = None
    for call in hass.services.async_register.call_args_list:
        args = call[0]
        if args[1] == SERVICE_SCAN_DEVICES:
            handler = args[2]
            break

    assert handler is not None

    hub = MagicMock(spec=ModbusHub)
    # Configure non-standard port to trigger Heuristic 1
    hub._config = {"name": "Test Hub", "host": "127.0.0.1", "port": 4196, "connection_type": "tcp"}
    hub._connection_type = "tcp"
    hub.connect = AsyncMock()
    hub._lock = asyncio.Lock()

    hass.data[DOMAIN]["hub_id"] = hub

    call = MagicMock()
    call.data = {
        "hub_id": "hub_id",
        "start_unit": 1,
        "end_unit": 2,
        "register": 0,
        "register_type": "holding",
        "timeout": 1.0,
        "retries": 0,
        "verbosity": "debug"
    }

    with patch("custom_components.ha_modbus_debugger.services.ModbusScanner") as MockScanner:
        scanner_instance = MockScanner.return_value

        # Simulate results for Heuristic 2: Hard Timeouts
        # Unit 1: Timeout (elapsed > 0.95 * timeout)
        # Unit 2: Timeout
        scanner_instance.scan_tcp = MagicMock(return_value=[
            {"unit_id": 1, "error": "Timeout", "elapsed": 1.01},
            {"unit_id": 2, "error": "Timeout", "elapsed": 0.99}
        ])

        response = await handler(call)

        # Check Heuristic 1: Non-standard port warning in trace
        trace = response.get("trace", [])
        port_warning = any("Using non-standard port 4196" in t for t in trace)
        assert port_warning, "Heuristic 1 (Port Warning) failed"

        # Check Heuristic 2: Tip for timeouts
        tip_warning = any("Tip: Devices timed out at the full limit" in t for t in trace)
        assert tip_warning, "Heuristic 2 (Timeout Tip) failed"

def test_scan_devices_heuristics():
    loop = asyncio.new_event_loop()
    loop.run_until_complete(async_test_scan_devices_heuristics())
    loop.close()
