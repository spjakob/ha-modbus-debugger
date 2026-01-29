"""Sensor platform for Modbus Debugger."""

from __future__ import annotations

import logging
import struct
from datetime import timedelta

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    DOMAIN,
    CONF_SENSORS,
    CONF_UNIT_ID,
    CONF_REGISTER,
    CONF_COUNT,
    CONF_DATA_TYPE,
    CONF_SCAN_INTERVAL,
    CONF_NAME,
    DATA_TYPE_INT16,
    DATA_TYPE_UINT16,
    DATA_TYPE_INT32,
    DATA_TYPE_UINT32,
    DATA_TYPE_FLOAT16,
    DATA_TYPE_FLOAT32,
    DATA_TYPE_STRING,
)
from .modbus import ModbusHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    if entry.entry_id not in hass.data[DOMAIN]:
        return

    hub: ModbusHub = hass.data[DOMAIN][entry.entry_id]
    sensors_config = entry.options.get(CONF_SENSORS, [])

    entities = []
    unit_ids = set()

    for config in sensors_config:
        unit_id = config[CONF_UNIT_ID]
        unit_ids.add(unit_id)
        coordinator = ModbusSensorCoordinator(hass, hub, config)
        # We need to await the first refresh so we have data?
        # Usually async_config_entry_first_refresh is used but we create coords dynamically.
        # We can just let it update in background.
        entities.append(ModbusSensor(coordinator, config, entry.entry_id))

    # Add stats sensors for each Unit ID
    for unit_id in unit_ids:
        entities.append(ModbusStatsSensor(hub, unit_id, entry.entry_id, "success"))
        entities.append(ModbusStatsSensor(hub, unit_id, entry.entry_id, "fail"))

    async_add_entities(entities)


class ModbusSensorCoordinator(DataUpdateCoordinator):
    """Coordinator to poll Modbus data."""

    def __init__(self, hass, hub, config):
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"Modbus Sensor {config[CONF_NAME]}",
            update_interval=timedelta(seconds=config.get(CONF_SCAN_INTERVAL, 30)),
        )
        self.hub = hub
        self.config = config

    async def _async_update_data(self):
        """Fetch data from Modbus."""
        unit_id = self.config[CONF_UNIT_ID]
        register = self.config[CONF_REGISTER]
        count = self.config.get(CONF_COUNT, 1)

        # Adjust count based on data type if user left it as default but chose 32-bit
        dtype = self.config[CONF_DATA_TYPE]
        if (
            dtype in [DATA_TYPE_INT32, DATA_TYPE_UINT32, DATA_TYPE_FLOAT32]
            and count < 2
        ):
            count = 2

        result = await self.hub.read_holding_registers(unit_id, register, count)

        if result is None:
            self.hub.report_stat(unit_id, success=False)
            raise UpdateFailed("Connection error")

        if result.isError():
            self.hub.report_stat(unit_id, success=False)
            raise UpdateFailed(f"Modbus Error: {result}")

        self.hub.report_stat(unit_id, success=True)
        return self._parse_data(result.registers)

    def _parse_data(self, registers):
        dtype = self.config[CONF_DATA_TYPE]

        try:
            if dtype == DATA_TYPE_INT16:
                return struct.unpack(">h", struct.pack(">H", registers[0]))[0]
            elif dtype == DATA_TYPE_UINT16:
                return registers[0]
            elif dtype == DATA_TYPE_INT32:
                if len(registers) < 2:
                    return 0
                val = (registers[0] << 16) | registers[1]
                return struct.unpack(">i", struct.pack(">I", val))[0]
            elif dtype == DATA_TYPE_UINT32:
                if len(registers) < 2:
                    return 0
                val = (registers[0] << 16) | registers[1]
                return val
            elif dtype == DATA_TYPE_FLOAT16:
                return float(struct.unpack(">e", struct.pack(">H", registers[0]))[0])
            elif dtype == DATA_TYPE_FLOAT32:
                if len(registers) < 2:
                    return 0.0
                val = (registers[0] << 16) | registers[1]
                return struct.unpack(">f", struct.pack(">I", val))[0]
            elif dtype == DATA_TYPE_STRING:
                chars = ""
                for r in registers:
                    b = struct.pack(">H", r)
                    for byte in b:
                        if 32 <= byte <= 126:
                            chars += chr(byte)
                return chars
        except Exception as e:
            _LOGGER.error("Error parsing data: %s", e)
            return None
        return registers[0]


class ModbusSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Modbus Sensor."""

    def __init__(self, coordinator, config, entry_id):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._config = config
        self._entry_id = entry_id
        self._attr_name = config[CONF_NAME]
        self._attr_unique_id = (
            f"{entry_id}_{config[CONF_UNIT_ID]}_{config[CONF_REGISTER]}"
        )

        # Device Info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{config[CONF_UNIT_ID]}")},
            name=f"Modbus Device {config[CONF_UNIT_ID]}",
            manufacturer="Generic Modbus",
            via_device=(DOMAIN, entry_id),
        )

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data


class ModbusStatsSensor(SensorEntity):
    """Sensor for Modbus Statistics."""

    def __init__(self, hub, unit_id, entry_id, stat_type):
        """Initialize the stats sensor."""
        self._hub = hub
        self._unit_id = unit_id
        self._stat_type = stat_type  # "success" or "fail"
        self._attr_name = f"Device {unit_id} {stat_type.capitalize()} Count"
        self._attr_unique_id = f"{entry_id}_{unit_id}_{stat_type}"
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{unit_id}")},
            name=f"Modbus Device {unit_id}",
            manufacturer="Generic Modbus",
            via_device=(DOMAIN, entry_id),
        )

    async def async_update(self):
        """Fetch new state data for the sensor."""
        stats = self._hub.get_stats(self._unit_id)
        self._attr_native_value = stats.get(self._stat_type, 0)
