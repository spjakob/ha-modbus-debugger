import sys
from unittest.mock import MagicMock


# Define dummy classes for inheritance
class MockEntity:
    pass


class MockCoordinatorEntity(MockEntity):
    def __init__(self, coordinator):
        self.coordinator = coordinator


class MockSensorEntity(MockEntity):
    pass


class MockDataUpdateCoordinator:
    def __init__(
        self,
        hass,
        logger,
        name,
        update_interval=None,
        update_method=None,
        request_refresh_debouncer=None,
    ):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None


class MockConfigEntry:
    def __init__(self, data=None, options=None, entry_id="test", title="test"):
        self.data = data or {}
        self.options = options or {}
        self.entry_id = entry_id
        self.title = title


# Mock homeassistant module structure
sys.modules["homeassistant"] = MagicMock()
sys.modules["homeassistant.config_entries"] = MagicMock()
sys.modules["homeassistant.config_entries"].ConfigEntry = MockConfigEntry

sys.modules["homeassistant.const"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.helpers"] = MagicMock()
sys.modules["homeassistant.helpers.config_validation"] = MagicMock()
sys.modules["homeassistant.helpers.entity"] = MagicMock()
sys.modules["homeassistant.helpers.entity"].DeviceInfo = MagicMock()

sys.modules["homeassistant.helpers.entity_platform"] = MagicMock()

sys.modules["homeassistant.helpers.update_coordinator"] = MagicMock()
sys.modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = (
    MockCoordinatorEntity
)
sys.modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = (
    MockDataUpdateCoordinator
)

sys.modules["homeassistant.exceptions"] = MagicMock()

sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.sensor"] = MagicMock()
sys.modules["homeassistant.components.sensor"].SensorEntity = MockSensorEntity
sys.modules["homeassistant.components.sensor"].SensorDeviceClass = MagicMock()
sys.modules["homeassistant.components.sensor"].SensorStateClass = MagicMock()

sys.modules["homeassistant.data_entry_flow"] = MagicMock()

# Pymodbus is now installed in the environment, so we do NOT mock it here.
# This allows tests to interact with the real library classes (though we may still mock the network calls).
