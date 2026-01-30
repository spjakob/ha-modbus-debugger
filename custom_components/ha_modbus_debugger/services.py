"""Services for Modbus Debugger."""

import logging
import struct
import asyncio

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
        custom_timeout = float(call.data.get("custom_timeout", 3.0))
        custom_retries = int(call.data.get("custom_retries", 3))
        custom_concurrency = int(call.data.get("custom_concurrency", 10))
        log_to_file = call.data.get("log_to_file", False)
        # Default True for suppression
        disable_pymodbus_logging = call.data.get("disable_pymodbus_logging", True)

        verbosity = call.data.get("verbosity", "basic")
        show_trace = verbosity in ["detailed", "debug"]
        show_debug = verbosity == "debug"

        trace_log = []
        target_info = f"{hub._config.get('host')}:{hub._config.get('port')}" if 'host' in hub._config else f"{hub._config.get('port')} (Serial)"

        # Profile Parsing
        timeout = 0.1
        retries = 0
        concurrency = 50
        is_async = True

        if scan_profile == "sync_quick":
            timeout = 0.1
            retries = 0
            concurrency = 1
            is_async = False
        elif scan_profile in ["custom_async", "custom_sync"]:
            timeout = custom_timeout
            retries = custom_retries
            concurrency = custom_concurrency
            is_async = (scan_profile == "custom_async")

        # Calculate estimate
        num_units = end_unit - start_unit + 1
        est_time = (num_units * timeout * (retries + 1)) / concurrency

        if show_trace:
            trace_log.append(
                f"Starting scan on {hub._config.get('name')} ({target_info}). Range {start_unit}-{end_unit}. Profile: {scan_profile}"
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

        # Log to file setup
        original_logger_level = _LOGGER.level
        if log_to_file:
            if show_debug:
                _LOGGER.setLevel(logging.DEBUG)
            elif verbosity == "detailed":
                _LOGGER.setLevel(logging.INFO)

            _LOGGER.info(
                "Starting Modbus Scan... Range: %s-%s, Profile: %s. Params: Timeout=%.2fs, Retries=%d, Concurrency=%d. Estimated time: %.2fs. (Pymodbus logging: %s)",
                start_unit,
                end_unit,
                scan_profile,
                timeout,
                retries,
                concurrency,
                est_time,
                "Suppressed" if disable_pymodbus_logging else "Enabled"
            )

        # Suppress logging
        pymodbus_logger = logging.getLogger("pymodbus")
        original_level = pymodbus_logger.level
        if disable_pymodbus_logging:
            pymodbus_logger.setLevel(logging.CRITICAL)

        # Adjust timeout on the client (Retries handled via kwargs)
        old_timeout = None
        old_retries = None
        comm_params = None

        if hub._client:
            # Handle different Pymodbus versions
            if hasattr(hub._client, "comm_params"):
                comm_params = hub._client.comm_params

                # Update Timeout
                if hasattr(comm_params, "timeout"):
                    old_timeout = comm_params.timeout
                    comm_params.timeout = timeout
                elif hasattr(comm_params, "timeout_connect"):
                    old_timeout = comm_params.timeout_connect
                    comm_params.timeout_connect = timeout

        found_devices = []
        semaphore = asyncio.Semaphore(concurrency)

        async def scan_unit(unit_id):
            async with semaphore:
                # IMPORTANT: Reset error count to prevent auto-close logic in Pymodbus
                if hub._client:
                    if hasattr(hub._client, "state"):
                        hub._client.state.error_count = 0

                # Retry logic - handled manually here because we want fast fail,
                # but we also pass retries=0 to pymodbus to prevent internal retries.
                # The manual loop here is only for our OWN control if we wanted to implement custom retry logic,
                # but "retries=0" means 1 attempt. "retries=1" means 2 attempts.
                # So we loop range(retries + 1).

                for attempt in range(retries + 1):
                    if log_to_file and show_debug:
                        _LOGGER.debug("Sending request to Unit %s (Attempt %d/%d)", unit_id, attempt + 1, retries + 1)

                    # Pass retries=0 to underlying call to ensure it fails fast per attempt
                    if register_type == "input":
                        result = await hub.read_input_registers(unit_id, register, 1, retries=0)
                    else:
                        result = await hub.read_holding_registers(unit_id, register, 1, retries=0)

                    if log_to_file and show_debug:
                        _LOGGER.debug(
                            "Received response from Unit %s: %s", unit_id, result
                        )

                    if result is not None and not result.isError():
                        val = result.registers[0]
                        found_devices.append(
                            {
                                "unit_id": unit_id,
                                "register": register,
                                "value": val,
                                "hex": f"0x{val:04X}",
                            }
                        )
                        if show_trace:
                            trace_log.append(f"Unit {unit_id}: Found (Value {val})")
                        return  # Success

                    # If failed, we loop to retry.
                    if attempt == retries:
                        if show_debug:
                            trace_log.append(f"Unit {unit_id}: No Response")

        tasks = []
        for unit_id in range(start_unit, end_unit + 1):
            tasks.append(scan_unit(unit_id))

        if is_async:
            await asyncio.gather(*tasks)
        else:
            for t in tasks:
                await t

        # Restore logging and timeout
        if disable_pymodbus_logging:
            pymodbus_logger.setLevel(original_level)

        if log_to_file:
            _LOGGER.info("Modbus Scan Complete. Found %s devices.", len(found_devices))
            _LOGGER.setLevel(original_logger_level)

        # Restore Client Params
        if comm_params and old_timeout is not None:
            if hasattr(comm_params, "timeout"):
                comm_params.timeout = old_timeout
            elif hasattr(comm_params, "timeout_connect"):
                comm_params.timeout_connect = old_timeout

        return {
            "found_devices": sorted(found_devices, key=lambda x: x['unit_id']),
            "count": len(found_devices),
            "scanned_range": f"{start_unit}-{end_unit}",
            "trace": trace_log if show_trace else [],
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_SCAN_DEVICES,
        handle_scan_devices,
        supports_response=SupportsResponse.ONLY,
    )
