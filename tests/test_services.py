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

    # Mock async_add_executor_job to run the function immediately (sync)
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
    hub.connect = AsyncMock(return_value=True)
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

    # Patch ModbusScanner in services.py
    with patch("custom_components.ha_modbus_debugger.services.ModbusScanner") as MockScanner:
        scanner_instance = MockScanner.return_value

        # Mock read_registers_tcp (Sync)
        scanner_instance.read_registers_tcp = MagicMock(return_value={
            "registers": [0x1234],
            "unit_id": 1
        })

        response = await handler(call)

        assert response["registers"] == [0x1234]
        assert response["hex"] == ["0x1234"]
        # Verify table structure
        assert "table" in response
        assert response["table"][0]["address"] == 10
        assert response["table"][0]["value"] == 0x1234

        # Verify call
        scanner_instance.read_registers_tcp.assert_called_once()
        args, kwargs = scanner_instance.read_registers_tcp.call_args
        # unit, reg, count, type, timeout, retries, cb
        assert args[0] == 1
        assert args[1] == 10
        assert args[2] == 1
        assert abs(args[4] - 2.0) < 0.001

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

        assert len(response["registers"]) == 2
        assert response["uint32_be"] == [65538]
        assert len(response["table"]) == 2
        assert response["table"][0]["address"] == 100
        assert response["table"][1]["address"] == 101
        assert response["table"][1]["value"] == 2

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
    hub.connect = AsyncMock(return_value=True)
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

        MockScanner.assert_called_with(hub._config)
        scanner_instance.scan_tcp.assert_called_once()
        args, kwargs = scanner_instance.scan_tcp.call_args
        # Default updated to 2.0? Yes in python code now
        # Wait, I updated services.py defaults to 2.0.
        assert abs(args[4] - 2.0) < 0.001
        assert args[5] == 0

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
    hub.connect = AsyncMock(return_value=True)
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

        start_call = None
        for call_args in mock_logger.info.call_args_list:
            if "Starting Modbus Scan" in call_args[0][0]:
                start_call = call_args
                break

        assert start_call is not None
        log_args = start_call[0][1:]
        assert log_args[0] == 1
        assert log_args[1] == 2
        assert abs(log_args[2] - 3.5) < 0.001
        assert log_args[3] == 1

        complete_call = None
        for call_args in mock_logger.info.call_args_list:
            if "Modbus Scan Complete" in call_args[0][0]:
                complete_call = call_args
                break
        assert complete_call is not None
        assert "scan_duration" in response

def test_scan_devices_custom_params_and_logging():
    loop = asyncio.new_event_loop()
    loop.run_until_complete(async_test_scan_devices_custom_params_and_logging())
    loop.close()
