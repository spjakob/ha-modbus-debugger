"""Scan Devices Action."""
import time
import logging
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse
from homeassistant.exceptions import ServiceValidationError

from ..modbus_core.client import SyncModbusClient, LateResponse
from ..modbus_core.exceptions import ModbusError, ModbusTimeoutError, ModbusExceptionResponseError
from ..modbus_core.heuristics import check_fast_timeout, check_non_standard_port, check_silent_gateway
from ..helpers.formatting import TraceLogger
from ..const import CONNECTION_TYPE_TCP, CONNECTION_TYPE_SERIAL

_LOGGER = logging.getLogger(__name__)

def _get_config_entry(hass: HomeAssistant, entry_id: str):
    """Get config entry by ID."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if not entry:
        raise ServiceValidationError(f"Hub {entry_id} not found.")
    return entry

def _run_scan_sync(config_data, start_unit, end_unit, register, reg_type_code, timeout, retries, verbosity, log_to_file):
    """Synchronous scan execution."""

    trace = TraceLogger()
    show_trace = verbosity in ["detailed", "debug"]
    show_debug = verbosity == "debug"

    # Log start
    target = f"{config_data.get('host', 'Serial')}:{config_data.get('port', '')}"
    if show_trace:
        trace.log(f"Starting scan on {config_data.get('name')} ({target}). Range {start_unit}-{end_unit}.")

    # Heuristics: Static checks
    warn_fast = check_fast_timeout(timeout)
    if warn_fast: trace.log(warn_fast)

    warn_port = check_non_standard_port(config_data.get('port', 0), config_data.get('connection_type'))
    if warn_port: trace.log(warn_port)

    # Initialize Client
    client = SyncModbusClient(
        connection_type=config_data.get('connection_type'),
        host=config_data.get('host') if config_data.get('connection_type') == CONNECTION_TYPE_TCP else config_data.get('port'),
        port=config_data.get('port') if config_data.get('connection_type') == CONNECTION_TYPE_TCP else 0,
        timeout=timeout,
        retries=retries,
        baudrate=config_data.get('baudrate', 9600),
        bytesize=config_data.get('bytesize', 8),
        parity=config_data.get('parity', 'N'),
        stopbits=config_data.get('stopbits', 1),
        rtu_over_tcp=config_data.get('rtu_over_tcp', False)
    )

    found_devices = []
    scan_results = [] # Store raw results for analysis

    # Trackers for Heuristics
    error_count = 0

    try:
        client.connect()

        # We assume holding register (0x03) vs input (0x04)
        # But 'reg_type_code' passed from service is usually 3 or 4.
        fc = reg_type_code

        # Read byte count for register reading (1 register = 2 bytes)
        # Actually we just want to read 1 register to check existence.
        # Data payload for execute?
        # Protocol build_tcp_request takes (unit, fc, data).
        # For Read Holding (03): Data is Start Addr (2 bytes) + Count (2 bytes).
        import struct
        req_data = struct.pack(">HH", register, 1) # Read 1 register at 'register'

        for unit_id in range(start_unit, end_unit + 1):

            # Check for Late Responses from previous iterations
            while client._late_responses:
                lr = client._late_responses.pop(0)
                msg = f"Unit {lr.unit_id}: Late Recovery (Ghost Data)!"
                if show_trace: trace.log(msg)
                scan_results.append({"unit_id": lr.unit_id, "status": "late_recovery"})
                found_devices.append({"unit_id": lr.unit_id, "value": "Late Recovery"})

            try:
                start_req = time.monotonic()
                resp = client.execute(unit_id, fc, req_data)
                elapsed = time.monotonic() - start_req

                # If we got here, we have data.
                # Parse value (1 register = 2 bytes)
                val = 0
                if len(resp) >= 2:
                    val = struct.unpack(">H", resp[:2])[0]

                msg = f"Unit {unit_id}: Found (Value {val})"
                if show_trace: trace.log(msg)

                scan_results.append({"unit_id": unit_id, "status": "ok", "elapsed": elapsed})
                found_devices.append({"unit_id": unit_id, "value": val, "elapsed": elapsed})

            except ModbusExceptionResponseError as e:
                # Device exists but returned exception
                elapsed = time.monotonic() - start_req
                msg = f"Unit {unit_id}: Exception Response (Code {e.code})"
                if show_trace: trace.log(msg)
                scan_results.append({"unit_id": unit_id, "status": "exception", "error": str(e), "elapsed": elapsed})
                found_devices.append({"unit_id": unit_id, "error": f"Exception Code {e.code}", "elapsed": elapsed})

            except ModbusTimeoutError:
                # Timeout
                elapsed = time.monotonic() - start_req
                if show_debug: trace.log(f"Unit {unit_id}: Timed out ({elapsed:.2f}s)")
                scan_results.append({"unit_id": unit_id, "status": "timeout", "elapsed": elapsed})
                error_count += 1

            except ModbusError as e:
                # Other error (CRC, Connection)
                elapsed = time.monotonic() - start_req
                if show_debug: trace.log(f"Unit {unit_id}: Error {e}")
                scan_results.append({"unit_id": unit_id, "status": "error", "error": str(e), "elapsed": elapsed})
                error_count += 1

        # Final check for Late Responses after loop
        while client._late_responses:
            lr = client._late_responses.pop(0)
            msg = f"Unit {lr.unit_id}: Late Recovery (Ghost Data) - After Scan"
            if show_trace: trace.log(msg)
            found_devices.append({"unit_id": lr.unit_id, "value": "Late Recovery"})

    except Exception as e:
        trace.log(f"Critical Scan Error: {e}")
    finally:
        client.close()

    # Heuristics: Post-Scan
    warn_silent = check_silent_gateway(len(found_devices), error_count, (end_unit - start_unit + 1))
    if warn_silent: trace.log(warn_silent)

    # Check Hard Timeouts
    hard_timeouts = [r for r in scan_results if r["status"] == "timeout" and r["elapsed"] >= (timeout * 0.95)]
    if len(hard_timeouts) > 0 and len(found_devices) == 0:
         trace.log("Tip: Multiple hard timeouts detected. This may indicate the timeout is too short for the gateway.")

    return {
        "found_devices": sorted(found_devices, key=lambda x: x.get('unit_id', 0)),
        "trace": trace.get_trace(),
        "count": len(found_devices)
    }

async def scan_devices(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """Handle the scan_devices service."""
    hub_id = call.data.get("hub_id")
    entry = _get_config_entry(hass, hub_id)

    start_unit = call.data.get("start_unit", 1)
    end_unit = call.data.get("end_unit", 10)
    register = call.data.get("register", 0)
    register_type = call.data.get("register_type", "holding")
    timeout = float(call.data.get("timeout", 2.0))
    retries = int(call.data.get("retries", 0))
    verbosity = call.data.get("verbosity", "basic")
    log_to_file = call.data.get("log_to_file", False)

    reg_type_code = 3 if register_type == "holding" else 4

    start_time = time.perf_counter()

    result = await hass.async_add_executor_job(
        _run_scan_sync,
        entry.data,
        start_unit,
        end_unit,
        register,
        reg_type_code,
        timeout,
        retries,
        verbosity,
        log_to_file
    )

    duration = time.perf_counter() - start_time
    result["scan_duration"] = duration
    result["scanned_range"] = f"{start_unit}-{end_unit}"

    return result
