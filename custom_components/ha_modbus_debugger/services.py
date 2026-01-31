"""Services for Modbus Debugger."""

import logging
import struct
import asyncio
import time

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN, CONNECTION_TYPE_SERIAL, CONNECTION_TYPE_TCP
from .modbus import ModbusHub
from .scanner import ModbusScanner, READ_HOLDING_REGISTERS, READ_INPUT_REGISTERS

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
        # Disable logging param ignored in custom scanner (internal logger used)

        verbosity = call.data.get("verbosity", "basic")
        show_trace = verbosity in ["detailed", "debug"]
        show_debug = verbosity == "debug"

        trace_log = []
        target_info = f"{hub._config.get('host')}:{hub._config.get('port')}" if 'host' in hub._config else f"{hub._config.get('port')} (Serial)"

        # Profile Parsing
        timeout = 0.1
        retries = 0
        concurrency = 50
        is_async = True # Affects TCP mostly

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

        # Map register type
        reg_type_code = READ_HOLDING_REGISTERS
        if register_type == "input":
            reg_type_code = READ_INPUT_REGISTERS

        # Calculate estimate
        num_units = end_unit - start_unit + 1
        est_time = (num_units * timeout * (retries + 1)) / concurrency
        if not is_async and hub._connection_type == CONNECTION_TYPE_TCP:
             # Sync TCP is sequential
             est_time = (num_units * timeout * (retries + 1))

        if show_trace:
            trace_log.append(
                f"Starting scan on {hub._config.get('name')} ({target_info}). Range {start_unit}-{end_unit}. Profile: {scan_profile}"
            )

        # Log to file setup
        original_logger_level = _LOGGER.level
        if log_to_file:
            if show_debug:
                _LOGGER.setLevel(logging.DEBUG)
            elif verbosity == "detailed":
                _LOGGER.setLevel(logging.INFO)

            _LOGGER.info(
                "Starting Modbus Scan (Custom Scanner)... Range: %s-%s, Profile: %s. Params: Timeout=%.2fs, Retries=%d, Concurrency=%d.",
                start_unit,
                end_unit,
                scan_profile,
                timeout,
                retries,
                concurrency
            )

        # Initialize Scanner
        scanner = ModbusScanner(hub._config)

        # Determine Execution Strategy
        scan_results = []
        scan_start_time = time.perf_counter()

        def update_trace(res):
            if show_trace:
                if "value" in res and res["value"] is not None:
                     trace_log.append(f"Unit {res['unit_id']}: Found (Value {res['value']})")
                elif "error" in res:
                     # Show errors if debug, or if it's a specific Modbus exception
                     if "Exception Code" in res.get("error", ""):
                         trace_log.append(f"Unit {res['unit_id']}: Exception Response ({res['error']})")
                     elif show_debug:
                         trace_log.append(f"Unit {res['unit_id']}: {res['error']}")

        # Prepare for Scan - manage shared resource (Serial)
        async with hub._lock:
            # If Serial, we MUST close the hub's connection to free the port
            was_connected = False
            if hub._connection_type == CONNECTION_TYPE_SERIAL:
                if hub._client and hub._client.connected:
                    was_connected = True
                    if show_trace: trace_log.append("Closing existing Serial connection for exclusive scan access...")
                    await hub.close()

            try:
                if hub._connection_type == CONNECTION_TYPE_TCP:
                    if is_async:
                        scan_results = await scanner.scan_tcp(
                            start_unit, end_unit, register, reg_type_code,
                            timeout, retries, concurrency, update_callback=update_trace
                        )
                    else:
                        # Sync scan for TCP - we reuse the implementation but concurrency=1
                        scan_results = await scanner.scan_tcp(
                            start_unit, end_unit, register, reg_type_code,
                            timeout, retries, 1, update_callback=update_trace
                        )
                elif hub._connection_type == CONNECTION_TYPE_SERIAL:
                    # Serial is blocking, run in executor
                    if show_trace: trace_log.append("Starting Serial Scan (Blocking)...")
                    scan_results = await hass.async_add_executor_job(
                        scanner.scan_serial,
                        start_unit, end_unit, register, reg_type_code,
                        timeout, retries, update_trace
                    )
            except Exception as e:
                _LOGGER.error("Scan failed: %s", e)
                if show_trace: trace_log.append(f"Critical Scan Error: {e}")
                scan_results = [{"error": str(e)}]
            finally:
                # We don't need to explicitly reconnect serial, Hub does it on demand.
                pass

        scan_duration = time.perf_counter() - scan_start_time

        # Format Results
        found_devices = []
        for res in scan_results:
            if "error" not in res or "Exception Code" in res.get("error", ""):
                 # Include successful reads AND Modbus Exceptions (Device present)
                 # If it's an exception, value is None.
                 found_devices.append(res)

        if log_to_file:
            _LOGGER.info("Modbus Scan Complete. Found %s devices. Duration: %.2fs", len(found_devices), scan_duration)
            _LOGGER.setLevel(original_logger_level)

        return {
            "found_devices": sorted(found_devices, key=lambda x: x.get('unit_id', 0)),
            "count": len(found_devices),
            "scanned_range": f"{start_unit}-{end_unit}",
            "scan_duration": scan_duration,
            "trace": trace_log if show_trace else [],
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_SCAN_DEVICES,
        handle_scan_devices,
        supports_response=SupportsResponse.ONLY,
    )
