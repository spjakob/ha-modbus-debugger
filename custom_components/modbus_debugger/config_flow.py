"""Config flow for Modbus Debugger."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_CONNECTION_TYPE,
    CONF_HOST,
    CONF_PORT,
    CONF_BAUDRATE,
    CONF_PARITY,
    CONF_STOPBITS,
    CONF_BYTESIZE,
    CONF_BYTESIZE,
    CONF_NAME,
    CONNECTION_TYPE_TCP,
    CONNECTION_TYPE_SERIAL,
    DEFAULT_PORT,
    DEFAULT_BAUDRATE,
    CONF_RTU_OVER_TCP,
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Modbus Debugger."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_NAME): str,
                        vol.Required(
                            CONF_CONNECTION_TYPE, default=CONNECTION_TYPE_TCP
                        ): vol.In([CONNECTION_TYPE_TCP, CONNECTION_TYPE_SERIAL]),
                    }
                ),
            )

        self._name = user_input[CONF_NAME]
        if not self._name:
             self._name = "Modbus Debugger"

        if user_input[CONF_CONNECTION_TYPE] == CONNECTION_TYPE_TCP:
            return await self.async_step_tcp()
        return await self.async_step_serial()

    async def async_step_tcp(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle TCP configuration."""
        if user_input is None:
            return self.async_show_form(
                step_id="tcp",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_HOST): str,
                        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                        vol.Optional(CONF_RTU_OVER_TCP, default=False): bool,
                    }
                ),
            )

        return self.async_create_entry(
            title=self._name,
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP,
                CONF_NAME: self._name,
                **user_input,
            },
        )

    async def async_step_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle Serial configuration."""
        if user_input is None:
            return self.async_show_form(
                step_id="serial",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_PORT): str,
                        vol.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): vol.In(
                            [1200, 2400, 4800, 9600, 14400, 19200, 38400, 57600, 115200]
                        ),
                        vol.Required("serial_mode", default="8N1"): vol.In(
                            ["8N1", "8E1", "8O1", "8N2", "7E1", "7O1"]
                        ),
                    }
                ),
            )

        # Parse serial_mode
        mode = user_input.pop("serial_mode")
        bytesize = int(mode[0])
        parity = mode[1]
        stopbits = int(mode[2])

        return self.async_create_entry(
            title=self._name,
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_SERIAL,
                CONF_NAME: self._name,
                CONF_BYTESIZE: bytesize,
                CONF_PARITY: parity,
                CONF_STOPBITS: stopbits,
                **user_input,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        return await self.async_step_edit_connection()

    async def async_step_menu(self, user_input=None):
        """Show the menu."""
        return self.async_show_menu(
            step_id="menu",
            menu_options=[
                "edit_connection",
            ],
        )

    async def async_step_edit_connection(self, user_input=None):
        """Edit connection settings."""
        connection_type = self._config_entry.data.get(
            CONF_CONNECTION_TYPE, CONNECTION_TYPE_TCP
        )

        if user_input is not None:
            # We must update the main config entry data
            new_data = self._config_entry.data.copy()
            new_data.update(user_input)
            self.hass.config_entries.async_update_entry(
                self._config_entry, data=new_data
            )
            # Reload entry to apply changes
            await self.hass.config_entries.async_reload(self._config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        current_port = self._config_entry.data.get(CONF_PORT)
        if connection_type == CONNECTION_TYPE_SERIAL:
            schema = vol.Schema(
                {
                    vol.Required(CONF_PORT, default=current_port): str,
                }
            )
        else:
            current_host = self._config_entry.data.get(CONF_HOST)
            schema = vol.Schema(
                {
                    vol.Required(CONF_HOST, default=current_host): str,
                    vol.Required(CONF_PORT, default=current_port): int,
                }
            )

        return self.async_show_form(
            step_id="edit_connection",
            data_schema=schema,
        )
