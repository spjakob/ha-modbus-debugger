"""Services for Modbus Debugger."""

import logging
import struct

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN
from .modbus import ModbusHub

_LOGGER = logging.getLogger(__name__)

SERVICE_READ_REGISTER = "read_register"


async def setup_services(hass: HomeAssistant):
    """Set up the services for the Modbus Debugger integration."""
    if hass.services.has_service(DOMAIN, SERVICE_READ_REGISTER):
        return

    async def handle_read_register(call: ServiceCall) -> ServiceResponse:
        """Handle the read_register service."""
        hub_id = call.data.get("hub_id")
        unit_id = call.data.get("unit_id", 1)
        register = call.data["register"]
        count = call.data.get("count", 1)
        register_type = call.data.get("register_type", "holding")

        # Select Hub
        hubs = hass.data.get(DOMAIN, {})
        if not hubs:
            raise ServiceValidationError("No Modbus Hubs configured.")

        hub: ModbusHub = None
        if hub_id:
            hub = hubs.get(hub_id)
            if not hub:
                raise ServiceValidationError(f"Hub {hub_id} not found.")
        else:
            # Default to the first one if only one exists
            if len(hubs) == 1:
                hub = next(iter(hubs.values()))
            else:
                # Try to match by config entry id if passed as simple string, though selector returns ID
                pass
                if not hub:
                    raise ServiceValidationError(
                        "Multiple hubs found. Please specify hub_id."
                    )

        # Perform Read
        if register_type == "input":
            result = await hub.read_input_registers(unit_id, register, count)
        else:
            result = await hub.read_holding_registers(unit_id, register, count)

        if result is None:
            raise ServiceValidationError(
                "Failed to read from Modbus device (Connection Error)."
            )

        if result.isError():
            raise ServiceValidationError(f"Modbus Error: {result}")

        # Parse Result
        registers = result.registers
        response = {
            "registers": registers,
            "hex": [f"0x{r:04X}" for r in registers],
            "debug_info": f"Read {count} registers from Unit {unit_id}, Address {register} ({register_type}). Success.",
        }

        # Conversions
        # 16-bit
        response["int16"] = [
            struct.unpack(">h", struct.pack(">H", r))[0] for r in registers
        ]
        response["uint16"] = registers

        # Float16 (IEEE 754 Half)
        try:
            response["float16"] = [
                float(struct.unpack(">e", struct.pack(">H", r))[0]) for r in registers
            ]
        except Exception:
            response["float16"] = []

        # 32-bit (Combine pairs)
        if count >= 2:
            int32_be = []
            uint32_be = []
            float32_be = []

            int32_le = []  # Little Endian Word Swap
            float32_le = []

            for i in range(0, len(registers) - 1, 2):
                # Big Endian: reg[i] << 16 | reg[i+1]
                val_be = (registers[i] << 16) | registers[i + 1]
                int32_be.append(struct.unpack(">i", struct.pack(">I", val_be))[0])
                uint32_be.append(val_be)
                float32_be.append(struct.unpack(">f", struct.pack(">I", val_be))[0])

                # Little Endian (Word Swap): reg[i+1] << 16 | reg[i]
                val_le = (registers[i + 1] << 16) | registers[i]
                int32_le.append(struct.unpack(">i", struct.pack(">I", val_le))[0])
                float32_le.append(struct.unpack(">f", struct.pack(">I", val_le))[0])

            response["int32_be"] = int32_be
            response["uint32_be"] = uint32_be
            response["float32_be"] = float32_be

            response["int32_le_swap"] = int32_le
            response["float32_le_swap"] = float32_le

        # Char/String
        # Treat each register as 2 chars
        chars = ""
        for r in registers:
            b = struct.pack(">H", r)
            for byte in b:
                if 32 <= byte <= 126:  # Printable
                    chars += chr(byte)
                else:
                    chars += "."
        response["string"] = chars

        return response

    hass.services.async_register(
        DOMAIN,
        SERVICE_READ_REGISTER,
        handle_read_register,
        supports_response=SupportsResponse.ONLY,
    )
