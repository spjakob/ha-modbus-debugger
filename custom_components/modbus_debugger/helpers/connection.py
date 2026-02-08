"""Connection Helper."""

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from ..modbus_core.client import SyncModbusClient
from ..const import CONNECTION_TYPE_TCP, DOMAIN


def get_config_entry(hass: HomeAssistant, entry_id: str | None = None):
    """Get config entry by ID or find default."""
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if not entry:
            raise ServiceValidationError(f"Hub {entry_id} not found.")
        return entry

    # No ID provided, try to find a default
    # User feedback: Explicit selection is required.
    raise ServiceValidationError("No Hub ID provided. Please select a Modbus Hub.")


def get_client(config_data, timeout, retries):
    """Create and return a SyncModbusClient instance."""
    return SyncModbusClient(
        connection_type=config_data.get("connection_type"),
        host=config_data.get("host")
        if config_data.get("connection_type") == CONNECTION_TYPE_TCP
        else config_data.get("port"),
        port=config_data.get("port")
        if config_data.get("connection_type") == CONNECTION_TYPE_TCP
        else 0,
        timeout=timeout,
        retries=retries,
        baudrate=config_data.get("baudrate", 9600),
        bytesize=config_data.get("bytesize", 8),
        parity=config_data.get("parity", "N"),
        stopbits=config_data.get("stopbits", 1),
        rtu_over_tcp=config_data.get("rtu_over_tcp", False),
    )
