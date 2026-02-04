"""Actions Registry."""

import functools
from homeassistant.core import HomeAssistant, SupportsResponse
from .scan import scan_devices
from .read import read_register
from .stress import stress_test
from ..const import DOMAIN

SERVICE_SCAN_DEVICES = "scan_devices"
SERVICE_READ_REGISTER = "read_register"
SERVICE_STRESS_TEST = "stress_test_device"


async def register_services(hass: HomeAssistant):
    """Register Modbus Debugger services."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_SCAN_DEVICES,
        functools.partial(scan_devices, hass),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_READ_REGISTER,
        functools.partial(read_register, hass),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STRESS_TEST,
        functools.partial(stress_test, hass),
        supports_response=SupportsResponse.ONLY,
    )
