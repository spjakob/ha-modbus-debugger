"""The Modbus Debugger integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .modbus import ModbusHub
from .services import setup_services

PLATFORMS: list[Platform] = [Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Modbus Debugger from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    hub = ModbusHub(entry.data)
    # Attempt connection but don't fail setup if it fails (e.g. device offline)
    if not await hub.connect():
        _LOGGER.warning("Could not connect to Modbus Hub %s at setup", entry.title)

    hass.data[DOMAIN][entry.entry_id] = hub

    # Register the Hub Device so child devices can link to it
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Generic Modbus",
        model="Modbus Hub",
        configuration_url=f"http://{entry.data.get('host')}" if entry.data.get('host') else None,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await setup_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hub = hass.data[DOMAIN].pop(entry.entry_id)
        await hub.close()

    return unload_ok
