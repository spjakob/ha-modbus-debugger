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

    # Setup
    await setup_services(hass)

    # We now register TWO services. We need to find the read_register one.
    handler = None
    for call in hass.services.async_register.call_args_list:
        args = call[0]
        if args[1] == SERVICE_READ_REGISTER:
            handler = args[2]
            break

    assert handler is not None

    # Mock Hub
    hub = MagicMock(spec=ModbusHub)
    # Mock _config for verbose mode
    hub._config = {"name": "Test Hub"}
    hub.connect = AsyncMock(return_value=True)

    hub.read_holding_registers = AsyncMock()
    mock_result = MagicMock()
    mock_result.registers = [0x1234]
    mock_result.isError.return_value = False
    hub.read_holding_registers.return_value = mock_result

    hass.data[DOMAIN]["hub_id"] = hub

    # Mock Call
    call = MagicMock()
    call.data = {
        "hub_id": "hub_id",
        "unit_id": 1,
        "register": 10,
        "count": 1,
        "register_type": "holding",
    }

    response = await handler(call)

    assert response["registers"] == [0x1234]
    assert response["hex"] == ["0x1234"]

    # Test 32-bit parsing
    hub.read_holding_registers.return_value.registers = [0x0001, 0x0002]
    call.data["count"] = 2
    response = await handler(call)

    # 0x00010002 = 65538
    assert response["uint32_be"] == [65538]

    # LE Swap: 0x00020001 = 131073
    assert response["int32_le_swap"] == [131073]

def test_read_register_service():
    loop = asyncio.new_event_loop()
    loop.run_until_complete(async_test_read_register_service())
    loop.close()

async def async_test_scan_devices_service():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.services.async_register = MagicMock()
    hass.services.has_service.return_value = False

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
    hub._lock = asyncio.Lock() # Use real async lock
    
    hass.data[DOMAIN]["hub_id"] = hub

    call = MagicMock()
    call.data = {
        "hub_id": "hub_id",
        "start_unit": 1,
        "end_unit": 2,
        "register": 0,
        "register_type": "holding"
    }

    # Patch ModbusScanner in services.py
    with patch("custom_components.ha_modbus_debugger.services.ModbusScanner") as MockScanner:
        scanner_instance = MockScanner.return_value

        # Mock scan_tcp return value
        # Device 1: Found, Device 2: Missing (implicit in list)
        scanner_instance.scan_tcp = AsyncMock(return_value=[
            {"unit_id": 1, "register": 0, "value": 123, "hex": "0x007B"}
        ])

        response = await handler(call)

        assert response["count"] == 1
        assert response["found_devices"][0]["unit_id"] == 1
        assert response["found_devices"][0]["value"] == 123

        # Verify scanner was called with correct config
        MockScanner.assert_called_with(hub._config)
        scanner_instance.scan_tcp.assert_called_once()

def test_scan_devices_service():
    loop = asyncio.new_event_loop()
    loop.run_until_complete(async_test_scan_devices_service())
    loop.close()

async def async_test_scan_devices_custom_profile_and_logging():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.services.async_register = MagicMock()
    hass.services.has_service.return_value = False

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
        # Custom profile
        "scan_profile": "custom_async",
        "custom_timeout": 0.5,
        "custom_retries": 1,
        "custom_concurrency": 5,
        # Logging
        "log_to_file": True,
        "verbosity": "debug"
    }

    # Patch the logger in services module and ModbusScanner
    with patch("custom_components.ha_modbus_debugger.services._LOGGER") as mock_logger, \
         patch("custom_components.ha_modbus_debugger.services.ModbusScanner") as MockScanner:

        # Mock .level to allow reading/setting
        mock_logger.level = logging.WARNING

        scanner_instance = MockScanner.return_value
        scanner_instance.scan_tcp = AsyncMock(return_value=[
             {"unit_id": 1, "register": 0, "value": 123, "hex": "0x007B"}
        ])

        response = await handler(call)

        # Check scanner params passed
        scanner_instance.scan_tcp.assert_called_once()
        args, kwargs = scanner_instance.scan_tcp.call_args
        # Args: start, end, register, type, timeout, retries, concurrency
        assert args[0] == 1
        assert args[1] == 2
        assert abs(args[4] - 0.5) < 0.001 # Timeout
        assert args[5] == 1 # Retries
        assert args[6] == 5 # Concurrency

        # Verify logger calls
        # Find the call to info that contains "Starting Modbus Scan"
        start_call = None
        for call_args in mock_logger.info.call_args_list:
            if "Starting Modbus Scan" in call_args[0][0]:
                start_call = call_args
                break

        assert start_call is not None
        # Check arguments: start_unit, end_unit, profile, timeout, retries, concurrency
        # The new log message in services.py matches these
        log_args = start_call[0][1:]
        # Custom Scanner log has different arg count than previous implementation?
        # services.py: "Starting Modbus Scan (Custom Scanner)... Range: %s-%s, Profile: %s. Params: Timeout=%.2fs, Retries=%d, Concurrency=%d."
        # 6 format args
        assert log_args[0] == 1
        assert log_args[1] == 2
        assert log_args[2] == "custom_async"

        # Check "Modbus Scan Complete"
        complete_call = None
        for call_args in mock_logger.info.call_args_list:
            if "Modbus Scan Complete" in call_args[0][0]:
                complete_call = call_args
                break
        assert complete_call is not None
        assert "scan_duration" in response

def test_scan_devices_custom_profile_and_logging():
    loop = asyncio.new_event_loop()
    loop.run_until_complete(async_test_scan_devices_custom_profile_and_logging())
    loop.close()
