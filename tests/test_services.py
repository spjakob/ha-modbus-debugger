import pytest
from unittest.mock import AsyncMock, MagicMock
from custom_components.ha_modbus_debugger.services import setup_services
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

    # Get the handler
    # We assume it's the first call
    args = hass.services.async_register.call_args
    assert args is not None
    domain, service, handler = args[0]
    assert domain == DOMAIN
    assert service == "read_register"

    # Mock Hub
    hub = MagicMock(spec=ModbusHub)
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
    assert response["uint16"] == [0x1234]

    # Test 32-bit parsing
    hub.read_holding_registers.return_value.registers = [0x0001, 0x0002]
    call.data["count"] = 2
    response = await handler(call)

    # 0x00010002 = 65538
    assert response["uint32_be"] == [65538]

    # LE Swap: 0x00020001 = 131073
    assert response["int32_le_swap"] == [131073]
