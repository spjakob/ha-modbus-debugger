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
                # If multiple hubs, but none selected, default to first?
                # User asked: "Make sure to select first item in the drop down."
                # We can implement this logic here if hub_id is missing.
                hub = next(iter(hubs.values()))
                # raise ServiceValidationError("Multiple hubs found. Please specify hub_id.")
        return hub

    async def handle_read_register(call: ServiceCall) -> ServiceResponse:
        """Handle the read_register service."""
        hub = await get_hub(call)
        unit_id = call.data.get("unit_id", 1)
        register = call.data["register"]
        count = call.data.get("count", 1)
        register_type = call.data.get("register_type", "holding")
        data_type_filter = call.data.get("data_type", "all")

        timeout = float(call.data.get("timeout", 2.0))
        retries = int(call.data.get("retries", 0))

        # Always debug/detailed logic for read_register now (trace needed)
        show_debug = True

        trace_log = []

        # Target info
        target_info = f"{hub._config.get('host')}:{hub._config.get('port')}" if 'host' in hub._config else f"{hub._config.get('port')} (Serial)"

        # Heuristic 1: Non-standard port
        if 'port' in hub._config and hub._config['port'] != 502 and hub._config.get('connection_type') == CONNECTION_TYPE_TCP:
             trace_log.append(f"NOTE: Using non-standard port {hub._config['port']}. Standard Modbus TCP usually uses port 502. If you experience timeouts, check if your gateway requires port 502 to enable Modbus TCP mode.")

        trace_log.append(f"Target: {hub._config.get('name')} ({target_info})")

        # Map register type
        reg_type_code = READ_HOLDING_REGISTERS
        if register_type == "input":
            reg_type_code = READ_INPUT_REGISTERS

        scanner = ModbusScanner(hub._config)

        trace_log.append(f"Reading {count} register(s) from Unit {unit_id} Address {register} ({register_type}). Timeout={timeout}s, Retries={retries}.")

        result_data = None

        def log_internal(msg):
             if show_debug:
                 # Strip prefixes
                 clean_msg = msg
                 if clean_msg.startswith("DEBUG: "): clean_msg = clean_msg[7:]
                 if clean_msg.startswith("INFO: "): clean_msg = clean_msg[6:]
                 if clean_msg.startswith("WARNING: "): clean_msg = clean_msg[9:]
                 trace_log.append(clean_msg)

        # Execute Sync
        async with hub._lock:
             # Manage Serial Exclusive Access
             was_connected = False
             if hub._connection_type == CONNECTION_TYPE_SERIAL:
                 if hub._client and hub._client.connected:
                     was_connected = True
                     trace_log.append("Closing existing Serial connection...")
                     await hub.close()

             try:
                 if hub._connection_type == CONNECTION_TYPE_TCP:
                      result_data = await hass.async_add_executor_job(
                          scanner.read_registers_tcp,
                          unit_id, register, count, reg_type_code,
                          timeout, retries, log_internal
                      )
                 elif hub._connection_type == CONNECTION_TYPE_SERIAL:
                      result_data = await hass.async_add_executor_job(
                          scanner.read_registers_serial,
                          unit_id, register, count, reg_type_code,
                          timeout, retries, log_internal
                      )
             except Exception as e:
                  trace_log.append(f"Critical Error: {e}")
                  return {"error": str(e), "trace": trace_log}
             finally:
                 # Hub will reconnect on demand
                 pass

        if not result_data:
             return {"error": "Unknown Error", "trace": trace_log}

        if "error" in result_data:
             trace_log.append(f"Read Failed: {result_data['error']}")
             return {
                 "error": "Read Failed",
                 "reason": result_data["error"],
                 "trace": trace_log
             }

        registers = result_data.get("registers", [])

        trace_log.append(f"Success. Received {len(registers)} registers.")

        # Consolidated Table View
        table_data = []

        # Helper to determine step size
        # 16-bit types: step 1
        # 32-bit types: step 2
        # all: step 1 (show everything)
        step = 1
        if "32" in data_type_filter and data_type_filter != "all":
            step = 2

        i = 0
        while i < len(registers):
            val = registers[i]
            addr = register + i

            row = {"address": addr}

            # Populate based on filter
            if data_type_filter == "all" or data_type_filter in ["uint16", "int16", "hex", "bin", "char", "float16"]:
                if data_type_filter == "all" or data_type_filter == "int16":
                    row["int16"] = struct.unpack(">h", struct.pack(">H", val))[0]
                if data_type_filter == "all" or data_type_filter == "uint16":
                    row["uint16"] = val
                if data_type_filter == "all" or data_type_filter == "float16":
                    try:
                        row["float16"] = float(struct.unpack(">e", struct.pack(">H", val))[0])
                    except Exception:
                        row["float16"] = None
                if data_type_filter == "all" or data_type_filter == "hex":
                    row["hex"] = f"0x{val:04X}"
                if data_type_filter == "all" or data_type_filter == "bin":
                    row["bin"] = f"{val:016b}"
                if data_type_filter == "all" or data_type_filter == "char":
                    b = struct.pack(">H", val)
                    chars = ""
                    for byte in b:
                        if 32 <= byte <= 126: chars += chr(byte)
                        else: chars += "."
                    row["char"] = chars

            # 32-bit values
            if i + 1 < len(registers):
                next_val = registers[i+1]

                if data_type_filter == "all" or "32" in data_type_filter:
                    # Big Endian: reg[i] << 16 | reg[i+1]
                    val_be = (val << 16) | next_val

                    if data_type_filter == "all" or data_type_filter == "int32_be":
                        row["int32_be"] = struct.unpack(">i", struct.pack(">I", val_be))[0]
                    if data_type_filter == "all" or data_type_filter == "uint32_be":
                        row["uint32_be"] = val_be
                    if data_type_filter == "all" or data_type_filter == "float32_be":
                        row["float32_be"] = struct.unpack(">f", struct.pack(">I", val_be))[0]

                    # Little Endian Word Swap: reg[i+1] << 16 | reg[i]
                    val_le = (next_val << 16) | val

                    if data_type_filter == "all" or data_type_filter == "int32_le_swap":
                        row["int32_le_swap"] = struct.unpack(">i", struct.pack(">I", val_le))[0]
                    if data_type_filter == "all" or data_type_filter == "float32_le_swap":
                        row["float32_le_swap"] = struct.unpack(">f", struct.pack(">I", val_le))[0]

            table_data.append(row)
            i += step

        response = {
            "debug_info": f"Read {len(registers)} registers from Unit {unit_id}, Address {register}. Success.",
            "table": table_data,
            "trace": trace_log
        }

        return response

    async def handle_scan_devices(call: ServiceCall) -> ServiceResponse:
        """Handle the scan_devices service."""
        hub = await get_hub(call)
        start_unit = call.data.get("start_unit", 1)
        end_unit = call.data.get("end_unit", 247)
        register = call.data.get("register", 0)
        register_type = call.data.get("register_type", "holding")

        timeout = float(call.data.get("timeout", 2.0))
        retries = int(call.data.get("retries", 0))
        log_to_file = call.data.get("log_to_file", False)

        verbosity = call.data.get("verbosity", "basic")
        show_trace = verbosity in ["detailed", "debug"]
        show_debug = verbosity == "debug"

        trace_log = []
        target_info = f"{hub._config.get('host')}:{hub._config.get('port')}" if 'host' in hub._config else f"{hub._config.get('port')} (Serial)"

        # Heuristic 1: Non-standard port
        if 'port' in hub._config and hub._config['port'] != 502 and hub._config.get('connection_type') == CONNECTION_TYPE_TCP:
             trace_log.append(f"NOTE: Using non-standard port {hub._config['port']}. Standard Modbus TCP usually uses port 502. If you experience timeouts, check if your gateway requires port 502 to enable Modbus TCP mode.")

        # Heuristic: Fast Timeout Warning
        if timeout < 0.6:
             trace_log.append(f"WARNING: Timeout ({timeout}s) is very fast. Most Gateways need ~600ms to detect dead devices. If you use a timeout lower than the Gateway's internal limit, you will likely see 'Late Recovery' logs or missed devices.")

        # Map register type
        reg_type_code = READ_HOLDING_REGISTERS
        if register_type == "input":
            reg_type_code = READ_INPUT_REGISTERS

        # Calculate estimate (Sequential)
        num_units = end_unit - start_unit + 1
        est_time = (num_units * timeout * (retries + 1))

        if show_trace:
            trace_log.append(
                f"Starting scan on {hub._config.get('name')} ({target_info}). Range {start_unit}-{end_unit}."
            )

        # Log to file setup
        original_logger_level = _LOGGER.level
        if log_to_file:
            if show_debug:
                _LOGGER.setLevel(logging.DEBUG)
            elif verbosity == "detailed":
                _LOGGER.setLevel(logging.INFO)

            _LOGGER.info(
                "Starting Modbus Scan... Range: %s-%s. Params: Timeout=%.2fs, Retries=%d. Estimated time: %.2fs.",
                start_unit,
                end_unit,
                timeout,
                retries,
                est_time
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

        def log_internal(msg):
            # Mirror scanner events to file logger and trace
            if log_to_file and show_debug:
                 _LOGGER.debug(msg)

            if show_debug:
                 # Strip prefixes
                 clean_msg = msg
                 if clean_msg.startswith("DEBUG: "): clean_msg = clean_msg[7:]
                 if clean_msg.startswith("INFO: "): clean_msg = clean_msg[6:]
                 if clean_msg.startswith("WARNING: "): clean_msg = clean_msg[9:]
                 trace_log.append(clean_msg)

        # Prepare for Scan - manage shared resource (Serial)
        async with hub._lock:
            # If Serial, we MUST close the hub's connection to free the port
            was_connected = False
            if hub._connection_type == CONNECTION_TYPE_SERIAL:
                if hub._client and hub._client.connected:
                    was_connected = True
                    if show_trace: trace_log.append("Closing existing Serial connection for exclusive scan access...")
                    await hub.close()
            elif hub._connection_type == CONNECTION_TYPE_TCP:
                 # Even for TCP, if we want to reuse the socket logic, we don't necessarily need to close hub,
                 # but since we create a NEW socket in scanner, it's fine.
                 # Scanner logic is completely independent.
                 pass

            try:
                if hub._connection_type == CONNECTION_TYPE_TCP:
                    # Sync scan in executor
                    if show_trace: trace_log.append("Starting TCP Scan (Sync)...")
                    scan_results = await hass.async_add_executor_job(
                        scanner.scan_tcp,
                        start_unit, end_unit, register, reg_type_code,
                        timeout, retries, update_trace, log_internal
                    )
                elif hub._connection_type == CONNECTION_TYPE_SERIAL:
                    # Serial is blocking, run in executor
                    if show_trace: trace_log.append("Starting Serial Scan (Blocking)...")
                    scan_results = await hass.async_add_executor_job(
                        scanner.scan_serial,
                        start_unit, end_unit, register, reg_type_code,
                        timeout, retries, update_trace, log_internal
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
        hard_timeout_count = 0
        gateway_exception_count = 0

        for res in scan_results:
            # Analyze for Heuristic 2
            if "error" in res:
                 if "Exception Code" in res.get("error", ""):
                     gateway_exception_count += 1

                 # Check elapsed time if available
                 if "elapsed" in res:
                     # Hard timeout: elapsed >= timeout * 0.95
                     if res["elapsed"] >= (timeout * 0.95):
                         hard_timeout_count += 1

            if "error" not in res or "Exception Code" in res.get("error", ""):
                 # Include successful reads AND Modbus Exceptions (Device present)
                 # If it's an exception, value is None.
                 found_devices.append(res)

        # Apply Heuristic 2: Timeout Diagnosis Tip
        if hard_timeout_count > 0 and gateway_exception_count == 0:
             trace_log.append("Tip: Devices timed out at the full limit. This usually indicates either the Timeout setting is too low for your Gateway's response speed, or the Gateway is in 'Transparent Mode' (waiting for RS485 timeouts). Try increasing the Timeout or checking Gateway settings.")

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
