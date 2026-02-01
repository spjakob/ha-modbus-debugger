import pytest
import logging
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from custom_components.ha_modbus_debugger.services import setup_services, SERVICE_READ_REGISTER, SERVICE_SCAN_DEVICES
from custom_components.ha_modbus_debugger.const import DOMAIN
from custom_components.ha_modbus_debugger.modbus import ModbusHub
from homeassistant.core import SupportsResponse

async def async_test_read_register_data_filtering():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.services.async_register = MagicMock()
    # Force has_service to return False so setup_services registers the services
    hass.services.has_service.side_effect = lambda d, s: False

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
        if args[1] == SERVICE_READ_REGISTER:
            handler = args[2]
            break

    # Debug if failed
    if handler is None:
        print("Calls to async_register:", hass.services.async_register.call_args_list)

    assert handler is not None

    hub = MagicMock(spec=ModbusHub)
    hub._config = {"name": "Test Hub", "host": "127.0.0.1", "port": 502, "connection_type": "tcp"}
    hub._connection_type = "tcp"
    hub.connect = AsyncMock()
    hub._lock = asyncio.Lock()

    hass.data[DOMAIN]["hub_id"] = hub

    call = MagicMock()
    call.data = {
        "hub_id": "hub_id",
        "unit_id": 1,
        "register": 100,
        "count": 2,
        "register_type": "holding",
        "timeout": 2.0,
        "retries": 0,
        "data_type": "uint32_be" # Filter
    }

    with patch("custom_components.ha_modbus_debugger.services.ModbusScanner") as MockScanner:
        scanner_instance = MockScanner.return_value

        # 0x0001 0x0002 -> 65538
        scanner_instance.read_registers_tcp = MagicMock(return_value={
            "registers": [0x0001, 0x0002],
            "unit_id": 1
        })

        response = await handler(call)

        table = response["table"]

        # Should only contain 1 row because step=2 for 32-bit types
        assert len(table) == 1
        row = table[0]
        assert row["address"] == 100

        # Check filtered keys presence
        assert "uint32_be" in row
        assert row["uint32_be"] == 65538

        # Check non-selected keys absence
        assert "int16" not in row
        assert "hex" not in row
        assert "int32_be" not in row # only uint32_be selected

    # Test "all" filter (default)
    call.data["data_type"] = "all"
    with patch("custom_components.ha_modbus_debugger.services.ModbusScanner") as MockScanner:
        scanner_instance = MockScanner.return_value
        scanner_instance.read_registers_tcp = MagicMock(return_value={
            "registers": [0x0001, 0x0002],
            "unit_id": 1
        })

        response = await handler(call)
        table = response["table"]
        assert len(table) == 2 # Step 1 for "all"

        row1 = table[0]
        assert "int16" in row1
        assert "hex" in row1
        assert "uint32_be" in row1 # calculated because next reg exists

def test_read_register_data_filtering():
    loop = asyncio.new_event_loop()
    loop.run_until_complete(async_test_read_register_data_filtering())
    loop.close()
