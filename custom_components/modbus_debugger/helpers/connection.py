"""Connection Helper."""

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from ..modbus_core.client import SyncModbusClient
from ..const import CONNECTION_TYPE_TCP, DOMAIN, CONF_IS_DEFAULT


def get_config_entry(hass: HomeAssistant, entry_id: str | None = None):
    """Get config entry by ID or find default."""
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if not entry:
            raise ServiceValidationError(f"Hub {entry_id} not found.")
        return entry

    # No ID provided, try to find a default
    entries = hass.config_entries.async_entries(DOMAIN)

    if not entries:
        raise ServiceValidationError("No Modbus Debugger hubs configured.")

    if len(entries) == 1:
        return entries[0]

    # Check for explicit default
    default_entries = [e for e in entries if e.data.get(CONF_IS_DEFAULT, False)]

    if len(default_entries) == 1:
        return default_entries[0]

    if len(default_entries) > 1:
        # Ambiguous defaults (shouldn't happen with UI enforcement, but safe to check)
        # We just pick the first one marked as default in this edge case?
        # Or error out. Erroring is safer.
        raise ServiceValidationError(
            "Multiple hubs marked as default. Please select a specific hub."
        )

    # Multiple entries exist but none marked default
    raise ServiceValidationError(
        "Multiple hubs found and none marked as default. Please select a hub."
    )


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
