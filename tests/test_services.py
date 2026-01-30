import pytest
import logging
from unittest.mock import AsyncMock, MagicMock, patch
from custom_components.ha_modbus_debugger.services import setup_services, SERVICE_READ_REGISTER, SERVICE_SCAN_DEVICES
from custom_components.ha_modbus_debugger.const import DOMAIN
from custom_components.ha_modbus_debugger.modbus import ModbusHub
from homeassistant.core import SupportsResponse

@pytest.mark.asyncio
async def test_read_register_service():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.services.async_register = MagicMock()
    hass.services.has_service.return_value = False

    # Setup
    await setup_services(hass)

    # We now register TWO services. We need to find the read_register one.
    # hass.services.async_register.call_args gives the LAST call, which might be scan_devices.
    # We should iterate over call_args_list.

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

@pytest.mark.asyncio
async def test_scan_devices_service():
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
    hub._config = {"name": "Test Hub"}
    hub.connect = AsyncMock(return_value=True)
    hub.read_holding_registers = AsyncMock()

    # Mock _client for timeout setting
    hub._client = MagicMock()
    hub._client.comm_params = MagicMock()
    hub._client.comm_params.timeout = 3.0

    # Mock behavior: Device 1 responds, Device 2 fails/timeout
    # Device 1
    mock_res_1 = MagicMock()
    mock_res_1.registers = [123]
    mock_res_1.isError.return_value = False

    # Device 2 (timeout/error)
    mock_res_2 = MagicMock()
    mock_res_2.isError.return_value = True

    def side_effect(slave, address, count, **kwargs):
        if slave == 1:
            return mock_res_1
        return mock_res_2

    hub.read_holding_registers.side_effect = side_effect

    hass.data[DOMAIN]["hub_id"] = hub

    call = MagicMock()
    call.data = {
        "hub_id": "hub_id",
        "start_unit": 1,
        "end_unit": 2,
        "register": 0,
        "register_type": "holding"
    }

    response = await handler(call)

    assert response["count"] == 1
    assert response["found_devices"][0]["unit_id"] == 1
    assert response["found_devices"][0]["value"] == 123

@pytest.mark.asyncio
async def test_scan_devices_custom_profile_and_logging():
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
    hub._config = {"name": "Test Hub"}
    hub.connect = AsyncMock(return_value=True)
    hub.read_holding_registers = AsyncMock()

    # Mock _client for timeout setting
    hub._client = MagicMock()
    hub._client.comm_params = MagicMock()
    hub._client.comm_params.timeout = 5.0 # Initial timeout

    hass.data[DOMAIN]["hub_id"] = hub

    call = MagicMock()
    call.data = {
        "hub_id": "hub_id",
        "start_unit": 1,
        "end_unit": 2,
        "register": 0,
        "register_type": "holding",
        # Custom profile
        "scan_profile": "custom",
        "custom_timeout": 0.5,
        "custom_retries": 1,
        "custom_concurrency": 5,
        # Logging
        "log_to_file": True,
        "verbosity": "debug"
    }

    # Mock result to allow scan to proceed
    mock_res = MagicMock()
    mock_res.registers = [123]
    mock_res.isError.return_value = False
    hub.read_holding_registers.return_value = mock_res

    # Patch the logger in services module
    with patch("custom_components.ha_modbus_debugger.services._LOGGER") as mock_logger:
        # Mock .level to allow reading/setting
        mock_logger.level = logging.WARNING

        response = await handler(call)

        # Check timeout was updated to custom value (0.5)
        # Note: The code sets comm_params.timeout temporarily then restores it.
        # But during the execution it should have been set.
        # Since we can't inspect "during", we rely on the fact that if it wasn't restored,
        # it would be stuck at 0.5. Or we check that the logic *attempted* to set it.
        # Actually, since it's an async function and we aren't pausing,
        # we can check that `comm_params.timeout` ends up back at 5.0 (restored).
        assert hub._client.comm_params.timeout == 5.0

        # Verify logger calls
        # 1. Start message with estimate
        # Estimate: (2 units * 0.5 timeout * (1+1 retries)) / 5 concurrency = (2 * 0.5 * 2) / 5 = 2.0 / 5 = 0.4 seconds
        # Wait, start=1, end=2 -> 2 units.
        # Est = (2 * 0.5 * 2) / 5 = 0.4s.

        # Find the call to info that contains "Starting Modbus Scan"
        start_call = None
        for call_args in mock_logger.info.call_args_list:
            if "Starting Modbus Scan" in call_args[0][0]:
                start_call = call_args
                break

        assert start_call is not None
        # Check arguments: start_unit, end_unit, profile, est_time
        args = start_call[0][1:] # skip format string
        assert args[0] == 1
        assert args[1] == 2
        assert args[2] == "custom"
        assert abs(args[3] - 0.4) < 0.001

        # 2. Debug logs ("Sending request", "Received response")
        # Since we mocked log_to_file=True and verbosity=debug
        assert mock_logger.debug.called

        # Check "Modbus Scan Complete"
        complete_call = None
        for call_args in mock_logger.info.call_args_list:
            if "Modbus Scan Complete" in call_args[0][0]:
                complete_call = call_args
                break
        assert complete_call is not None
