import pytest
import logging
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from custom_components.ha_modbus_debugger.services import setup_services, SERVICE_READ_REGISTER, SERVICE_SCAN_DEVICES
from custom_components.ha_modbus_debugger.const import DOMAIN
from custom_components.ha_modbus_debugger.modbus import ModbusHub
from homeassistant.core import SupportsResponse

async def async_test_read_register_service():
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
        if args[1] == SERVICE_READ_REGISTER:
            handler = args[2]
            break

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
        "register": 10,
        "count": 1,
        "register_type": "holding",
        "timeout": 2.0,
        "retries": 0
    }

    with patch("custom_components.ha_modbus_debugger.services.ModbusScanner") as MockScanner:
        scanner_instance = MockScanner.return_value

        scanner_instance.read_registers_tcp = MagicMock(return_value={
            "registers": [0x1234],
            "unit_id": 1
        })

        response = await handler(call)

        # Verify cleaned up response structure (no top level lists)
        assert "registers" not in response
        assert "hex" not in response
        assert "int16" not in response
        assert "uint16" not in response

        # Verify table structure
        assert "table" in response
        row = response["table"][0]
        assert row["address"] == 10
        assert row["uint16"] == 0x1234
        assert row["int16"] == 0x1234
        assert row["hex"] == "0x1234"
        assert "value" not in row # Removed generic value key

        # Single register, so no 32-bit keys
        assert "int32_be" not in row

    # Test Range (Multiple registers)
    call.data["count"] = 2
    call.data["register"] = 100

    with patch("custom_components.ha_modbus_debugger.services.ModbusScanner") as MockScanner:
        scanner_instance = MockScanner.return_value
        scanner_instance.read_registers_tcp = MagicMock(return_value={
            "registers": [0x0001, 0x0002],
            "unit_id": 1
        })

        response = await handler(call)

        table = response["table"]
        assert len(table) == 2

        # Row 1 (Address 100) -> Has next val (101) -> Should have 32-bit
        row1 = table[0]
        assert row1["address"] == 100
        assert row1["uint16"] == 1
        assert "int32_be" in row1
        assert row1["int32_be"] == 65538 # 0x00010002

        # Row 2 (Address 101) -> No next val -> No 32-bit
        row2 = table[1]
        assert row2["address"] == 101
        assert row2["uint16"] == 2
        assert "int32_be" not in row2

def test_read_register_service():
    loop = asyncio.new_event_loop()
    loop.run_until_complete(async_test_read_register_service())
    loop.close()

async def async_test_scan_devices_service():
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
    hub._config = {"name": "Test Hub", "host": "127.0.0.1", "port": 502, "connection_type": "tcp"}
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
        "register_type": "holding"
    }

    with patch("custom_components.ha_modbus_debugger.services.ModbusScanner") as MockScanner:
        scanner_instance = MockScanner.return_value
        scanner_instance.scan_tcp = MagicMock(return_value=[
            {"unit_id": 1, "register": 0, "value": 123, "hex": "0x007B"}
        ])

        response = await handler(call)

        assert response["count"] == 1
        assert response["found_devices"][0]["unit_id"] == 1
        assert response["found_devices"][0]["value"] == 123

def test_scan_devices_service():
    loop = asyncio.new_event_loop()
    loop.run_until_complete(async_test_scan_devices_service())
    loop.close()

async def async_test_scan_devices_custom_params_and_logging():
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
    hub._config = {"name": "Test Hub", "host": "127.0.0.1", "port": 502, "connection_type": "tcp"}
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
        "timeout": 3.5,
        "retries": 1,
        "log_to_file": True,
        "verbosity": "debug"
    }

    with patch("custom_components.ha_modbus_debugger.services._LOGGER") as mock_logger, \
         patch("custom_components.ha_modbus_debugger.services.ModbusScanner") as MockScanner:

        mock_logger.level = logging.WARNING
        scanner_instance = MockScanner.return_value
        scanner_instance.scan_tcp = MagicMock(return_value=[
             {"unit_id": 1, "register": 0, "value": 123, "hex": "0x007B"}
        ])

        response = await handler(call)

        scanner_instance.scan_tcp.assert_called_once()
        args, kwargs = scanner_instance.scan_tcp.call_args
        assert args[0] == 1
        assert args[1] == 2
        assert abs(args[4] - 3.5) < 0.001
        assert args[5] == 1

def test_scan_devices_custom_params_and_logging():
    loop = asyncio.new_event_loop()
    loop.run_until_complete(async_test_scan_devices_custom_params_and_logging())
    loop.close()
