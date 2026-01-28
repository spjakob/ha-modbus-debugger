"""Config flow for Modbus Debugger."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

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
    DEFAULT_BYTESIZE,
    DEFAULT_PARITY,
    DEFAULT_STOPBITS,
    DEFAULT_TIMEOUT,
    CONF_SENSORS,
    CONF_UNIT_ID,
    CONF_REGISTER,
    CONF_COUNT,
    CONF_DATA_TYPE,
    CONF_SCAN_INTERVAL,
    DATA_TYPE_INT16,
    DATA_TYPE_UINT16,
    DATA_TYPE_INT32,
    DATA_TYPE_UINT32,
    DATA_TYPE_FLOAT16,
    DATA_TYPE_FLOAT32,
    DATA_TYPE_STRING,
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
                        vol.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): int,
                        vol.Required(CONF_BYTESIZE, default=DEFAULT_BYTESIZE): int,
                        vol.Required(CONF_PARITY, default=DEFAULT_PARITY): vol.In(
                            ["N", "E", "O", "M", "S"]
                        ),
                        vol.Required(CONF_STOPBITS, default=DEFAULT_STOPBITS): int,
                        vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): int,
                    }
                ),
            )

        return self.async_create_entry(
            title=self._name,
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_SERIAL,
                CONF_NAME: self._name,
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
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        return await self.async_step_menu()

    async def async_step_menu(self, user_input=None):
        """Show the menu."""
        return self.async_show_menu(
            step_id="menu", menu_options=["add_sensor", "remove_sensor"]
        )

    async def async_step_add_sensor(self, user_input=None):
        """Add a sensor."""
        if user_input is not None:
            sensors = self.config_entry.options.get(CONF_SENSORS, []).copy()
            sensors.append(user_input)
            return self.async_create_entry(title="", data={CONF_SENSORS: sensors})

        return self.async_show_form(
            step_id="add_sensor",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Required(CONF_UNIT_ID, default=1): int,
                    vol.Required(CONF_REGISTER): int,
                    vol.Optional(CONF_COUNT, default=1): int,
                    vol.Required(CONF_DATA_TYPE, default=DATA_TYPE_INT16): vol.In(
                        [
                            DATA_TYPE_INT16,
                            DATA_TYPE_UINT16,
                            DATA_TYPE_INT32,
                            DATA_TYPE_UINT32,
                            DATA_TYPE_FLOAT16,
                            DATA_TYPE_FLOAT32,
                            DATA_TYPE_STRING,
                        ]
                    ),
                    vol.Optional(CONF_SCAN_INTERVAL, default=30): int,
                }
            ),
        )

    async def async_step_remove_sensor(self, user_input=None):
        """Remove a sensor."""
        sensors = self.config_entry.options.get(CONF_SENSORS, [])
        if not sensors:
            return await self.async_step_menu()

        if user_input is not None:
            # user_input['sensors'] is a list of strings (names) to remove
            to_remove = user_input.get("sensors", [])
            new_sensors = [s for s in sensors if s[CONF_NAME] not in to_remove]
            return self.async_create_entry(title="", data={CONF_SENSORS: new_sensors})

        # List of sensor names
        sensor_names = [s[CONF_NAME] for s in sensors]

        return self.async_show_form(
            step_id="remove_sensor",
            data_schema=vol.Schema(
                {vol.Required("sensors"): cv.multi_select(sensor_names)}
            ),
        )
