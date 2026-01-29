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
SERVICE_SCAN_DEVICES = "scan_devices"


async def setup_services(hass: HomeAssistant):
    """Set up the services for the Modbus Debugger integration."""
    if hass.services.has_service(DOMAIN, SERVICE_READ_REGISTER):
        return

    async def get_hub(call: ServiceCall) -> ModbusHub:
        hub_id = call.data.get("hub_id")
        hubs = hass.data.get(DOMAIN, {})
        if not hubs:
            raise ServiceValidationError("No Modbus Hubs configured.")

        hub: ModbusHub = None
        if hub_id:
            hub = hubs.get(hub_id)
            if not hub:
                raise ServiceValidationError(f"Hub {hub_id} not found.")
        else:
            if len(hubs) == 1:
                hub = next(iter(hubs.values()))
            else:
                raise ServiceValidationError(
                    "Multiple hubs found. Please specify hub_id."
                )
        return hub

    async def handle_read_register(call: ServiceCall) -> ServiceResponse:
        """Handle the read_register service."""
        hub = await get_hub(call)
        unit_id = call.data.get("unit_id", 1)
        register = call.data["register"]
        count = call.data.get("count", 1)
        register_type = call.data.get("register_type", "holding")

        verbosity = call.data.get("verbosity", "detailed")
        show_trace = verbosity in ["detailed", "debug"]
        show_debug = verbosity == "debug"

        trace_log = []

        # Target info
        target_info = f"{hub._config.get('host')}:{hub._config.get('port')}" if 'host' in hub._config else f"{hub._config.get('port')} (Serial)"

        if show_trace:
            trace_log.append(f"Target: {hub._config.get('name')} ({target_info})")
            trace_log.append("Verifying connection...")

        if not await hub.connect():
            error_msg = hub.last_error or "Unknown Error"
            if show_trace:
                trace_log.append(f"Connection Failed: {error_msg}")
                if "111" in str(error_msg) or "Refused" in str(error_msg):
                    trace_log.append("Check IP/Port. Ensure no other integration is holding the connection open.")
            return {
                "error": "Connection Failed",
                "reason": error_msg,
                "trace": trace_log,
            }

        if show_trace:
            trace_log.append("Connected.")
            if show_debug:
                trace_log.append(
                    f"Sending Read Request: Unit={unit_id}, Address={register}, Count={count}, Type={register_type}"
                )

        # Perform Read
        if register_type == "input":
            result = await hub.read_input_registers(unit_id, register, count)
        else:
            result = await hub.read_holding_registers(unit_id, register, count)

        if result is None:
            error_msg = hub.last_error or "Connection lost during read"
            if show_trace:
                trace_log.append(f"Read Failed: {error_msg}")

            return {
                "error": "Read Failed",
                "reason": error_msg,
                "trace": trace_log,
            }

        if result.isError():
            if show_trace:
                trace_log.append(f"Modbus Error Response: {result}")
            return {
                "error": "Modbus Error",
                "reason": str(result),
                "trace": trace_log,
            }

        if show_trace:
            trace_log.append(f"Success. Received {len(result.registers)} registers.")

        # Parse Result
        registers = result.registers
        response = {
            "registers": registers,
            "hex": [f"0x{r:04X}" for r in registers],
            "debug_info": f"Read {count} registers from Unit {unit_id}, Address {register} ({register_type}). Success.",
        }
        if show_trace:
            response["trace"] = trace_log

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

    async def handle_scan_devices(call: ServiceCall) -> ServiceResponse:
        """Handle the scan_devices service."""
        hub = await get_hub(call)
        start_unit = call.data.get("start_unit", 1)
        end_unit = call.data.get("end_unit", 247)
        register = call.data.get("register", 0)
        register_type = call.data.get("register_type", "holding")

        scan_profile = call.data.get("scan_profile", "async_quick")
        custom_timeout = call.data.get("custom_timeout", 3.0)
        custom_concurrency = call.data.get("custom_concurrency", 50)

        verbosity = call.data.get("verbosity", "basic")
        show_trace = verbosity in ["detailed", "debug"]
        show_debug = verbosity == "debug"

        # Determine settings based on profile
        if scan_profile == "custom":
            timeout = custom_timeout
            concurrency = custom_concurrency
            # Async if concurrency > 1? Actually the profile is "custom", logic below handles concurrency.
            is_async = True # Assume custom implies async capability, or we can treat concurrency=1 as sync.
        elif scan_profile == "sync_quick":
            timeout = 0.1
            concurrency = 1
            is_async = False
        else: # async_quick
            timeout = 0.1
            concurrency = 50
            is_async = True

        trace_log = []
        target_info = f"{hub._config.get('host')}:{hub._config.get('port')}" if 'host' in hub._config else f"{hub._config.get('port')} (Serial)"

        if show_trace:
            trace_log.append(
                f"Starting scan on {hub._config.get('name')} ({target_info}). Range {start_unit}-{end_unit}. Profile: {scan_profile} (Timeout={timeout}s, Concurrency={concurrency})"
            )
            trace_log.append("Verifying connection...")

        # Verify connection ONCE before scanning loop
        if not await hub.connect():
            error_msg = hub.last_error or "Unknown Connection Error"
            if show_trace:
                trace_log.append(f"Connection Failed: {error_msg}")
                if "111" in str(error_msg) or "Refused" in str(error_msg):
                    trace_log.append("Check IP/Port. Ensure no other integration is holding the connection open.")

            return {
                "error": "Connection Failed",
                "reason": error_msg,
                "trace": trace_log,
            }

        if show_trace:
            trace_log.append("Connected. Beginning scan loop...")

        # Suppress logging
        logging.getLogger("pymodbus").setLevel(logging.CRITICAL)

        # Apply timeout hack?
        # Since hub._client is shared, modifying timeout is risky if other ops happen.
        # But we are in a service call.
        # Ideally we create a NEW client for scanning or accept the risk.
        # hub._client.comm_params.timeout = timeout ?
        # Pymodbus 3.x stores params in comm_params.
        original_timeout = None
        try:
            if hasattr(hub._client, "comm_params"):
                 original_timeout = hub._client.comm_params.timeout_connect
                 hub._client.comm_params.timeout_connect = timeout
            # Also read timeout?
        except Exception:
            pass

        found_devices = []

        import asyncio

        async def scan_unit(unit_id):
            if register_type == "input":
                result = await hub.read_input_registers(unit_id, register, 1)
            else:
                result = await hub.read_holding_registers(unit_id, register, 1)

            if result is not None and not result.isError():
                val = result.registers[0]
                return {
                    "unit_id": unit_id,
                    "register": register,
                    "value": val,
                    "hex": f"0x{val:04X}",
                }
            return None

        try:
            if is_async and concurrency > 1:
                # Batch processing
                semaphore = asyncio.Semaphore(concurrency)

                async def sem_scan(uid):
                    async with semaphore:
                        return await scan_unit(uid)

                tasks = [sem_scan(uid) for uid in range(start_unit, end_unit + 1)]
                results = await asyncio.gather(*tasks)
                for res in results:
                    if res:
                        found_devices.append(res)
                        if show_trace:
                            trace_log.append(f"Unit {res['unit_id']}: Found")
                    elif show_debug:
                         # We can't easily log which ID failed in gather without wrapping, but order is preserved
                         pass
            else:
                # Serial loop
                for unit_id in range(start_unit, end_unit + 1):
                    res = await scan_unit(unit_id)
                    if res:
                        found_devices.append(res)
                        if show_trace:
                            trace_log.append(f"Unit {unit_id}: Found (Value {res['value']})")
                    elif show_debug:
                        trace_log.append(f"Unit {unit_id}: No Response")

        finally:
            # Restore logging
            logging.getLogger("pymodbus").setLevel(logging.NOTSET)
            # Restore timeout if possible
            if original_timeout and hasattr(hub._client, "comm_params"):
                 hub._client.comm_params.timeout_connect = original_timeout

        return {
            "found_devices": found_devices,
            "count": len(found_devices),
            "scanned_range": f"{start_unit}-{end_unit}",
            "trace": trace_log if show_trace else [],
            "estimated_time": f"{(end_unit - start_unit + 1) * timeout / (concurrency if is_async else 1):.2f}s"
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_SCAN_DEVICES,
        handle_scan_devices,
        supports_response=SupportsResponse.ONLY,
    )
