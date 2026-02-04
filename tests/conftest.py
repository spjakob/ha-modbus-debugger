import asyncio
import sys
from unittest.mock import MagicMock

import pytest_asyncio

from tests.mock_gateway import BUS, run_server


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
sys.modules[
    "homeassistant.helpers.update_coordinator"
].CoordinatorEntity = MockCoordinatorEntity
sys.modules[
    "homeassistant.helpers.update_coordinator"
].DataUpdateCoordinator = MockDataUpdateCoordinator

sys.modules["homeassistant.exceptions"] = MagicMock()

sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.sensor"] = MagicMock()
sys.modules["homeassistant.components.sensor"].SensorEntity = MockSensorEntity
sys.modules["homeassistant.components.sensor"].SensorDeviceClass = MagicMock()
sys.modules["homeassistant.components.sensor"].SensorStateClass = MagicMock()

sys.modules["homeassistant.data_entry_flow"] = MagicMock()

# Pymodbus is now installed in the environment, so we do NOT mock it here.
# This allows tests to interact with the real library classes (though we may still mock the network calls).


@pytest_asyncio.fixture(scope="function")
async def mock_modbus_server(unused_tcp_port):
    """Spin up the Mock Gateway on a random port for integration tests."""
    BUS.reset()
    # run_server blocks in pymodbus 3.x if not handled.
    # Use create_task to ensure it runs in background.
    task = asyncio.create_task(run_server(port=unused_tcp_port))

    # Wait for server to be ready
    for _ in range(20):
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", unused_tcp_port)
            writer.close()
            await writer.wait_closed()
            break
        except OSError:
            await asyncio.sleep(0.1)
    else:
        task.cancel()
        raise RuntimeError(f"Mock server failed to start on port {unused_tcp_port}")

    yield unused_tcp_port

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
