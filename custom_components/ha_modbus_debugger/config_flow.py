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
    CONF_TIMEOUT,
    CONF_NAME,
    CONNECTION_TYPE_TCP,
    CONNECTION_TYPE_SERIAL,
    DEFAULT_PORT,
    DEFAULT_BAUDRATE,
    DEFAULT_TIMEOUT,
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
                        vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): int,
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
                        vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): int,
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
        return await self.async_step_edit_connection(user_input)

    async def async_step_edit_connection(self, user_input=None):
        """Edit connection settings."""
        if user_input is not None:
            # We must update the main config entry data
            new_data = self._config_entry.data.copy()
            new_data.update(user_input)

            # Re-parse serial_mode if it's in user_input
            if "serial_mode" in user_input:
                mode = user_input.pop("serial_mode")
                new_data[CONF_BYTESIZE] = int(mode[0])
                new_data[CONF_PARITY] = mode[1]
                new_data[CONF_STOPBITS] = int(mode[2])
                new_data.update(user_input)

            self.hass.config_entries.async_update_entry(
                self._config_entry, data=new_data
            )
            return self.async_create_entry(title="", data={})

        conn_type = self._config_entry.data.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_TCP)

        if conn_type == CONNECTION_TYPE_TCP:
            return self.async_show_form(
                step_id="edit_connection",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_HOST, default=self._config_entry.data.get(CONF_HOST)): str,
                        vol.Required(CONF_PORT, default=self._config_entry.data.get(CONF_PORT, DEFAULT_PORT)): int,
                        vol.Optional(CONF_RTU_OVER_TCP, default=self._config_entry.data.get(CONF_RTU_OVER_TCP, False)): bool,
                        vol.Optional(CONF_TIMEOUT, default=self._config_entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)): int,
                    }
                ),
            )
        else:
            # Serial
            current_mode = f"{self._config_entry.data.get(CONF_BYTESIZE, 8)}{self._config_entry.data.get(CONF_PARITY, 'N')}{self._config_entry.data.get(CONF_STOPBITS, 1)}"
            return self.async_show_form(
                step_id="edit_connection",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_PORT, default=self._config_entry.data.get(CONF_PORT)): str,
                        vol.Required(CONF_BAUDRATE, default=self._config_entry.data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)): vol.In(
                            [1200, 2400, 4800, 9600, 14400, 19200, 38400, 57600, 115200]
                        ),
                        vol.Required("serial_mode", default=current_mode): vol.In(
                            ["8N1", "8E1", "8O1", "8N2", "7E1", "7O1"]
                        ),
                        vol.Optional(CONF_TIMEOUT, default=self._config_entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)): int,
                    }
                ),
            )
