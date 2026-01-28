import pytest
from unittest.mock import MagicMock
from custom_components.ha_modbus_debugger.sensor import ModbusSensorCoordinator
from custom_components.ha_modbus_debugger.const import (
    CONF_UNIT_ID,
    CONF_REGISTER,
    CONF_COUNT,
    CONF_DATA_TYPE,
    CONF_SCAN_INTERVAL,
    CONF_NAME,
    DATA_TYPE_INT16,
    DATA_TYPE_UINT32,
    DATA_TYPE_FLOAT32,
)


@pytest.mark.asyncio
async def test_coordinator_parsing():
    hass = MagicMock()
    hub = MagicMock()
    config = {
        CONF_NAME: "test",
        CONF_UNIT_ID: 1,
        CONF_REGISTER: 10,
        CONF_COUNT: 1,
        CONF_DATA_TYPE: DATA_TYPE_INT16,
        CONF_SCAN_INTERVAL: 30,
    }

    coord = ModbusSensorCoordinator(hass, hub, config)

    # Test Int16
    assert coord._parse_data([0xFFFF]) == -1  # Signed 16-bit

    # Test UInt32
    coord.config[CONF_DATA_TYPE] = DATA_TYPE_UINT32
    assert coord._parse_data([0x0001, 0x0002]) == 65538

    # Test Float32
    # 1.0 in float32 is 0x3f800000
    # 0x3f80 = 16256
    # 0x0000 = 0
    coord.config[CONF_DATA_TYPE] = DATA_TYPE_FLOAT32
    assert coord._parse_data([16256, 0]) == 1.0
