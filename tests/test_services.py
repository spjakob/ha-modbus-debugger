import pytest
from unittest.mock import AsyncMock, MagicMock
from custom_components.ha_modbus_debugger.services import setup_services, SERVICE_READ_REGISTER, SERVICE_SCAN_DEVICES
from custom_components.ha_modbus_debugger.const import DOMAIN
from custom_components.ha_modbus_debugger.modbus import ModbusHub


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
        "register_type": "holding",
        # Use sync profile for test to avoid complex mocking of asyncio.gather/Semaphore
        "scan_profile": "sync_quick"
    }

    response = await handler(call)

    assert response["count"] == 1
    assert response["found_devices"][0]["unit_id"] == 1
    assert response["found_devices"][0]["value"] == 123
