"""Scan Devices Action (Synchronous execution with heuristics)."""


import time
import logging
import struct
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse

from ..modbus_core.exceptions import (
    ModbusError,
    ModbusTimeoutError,
    ModbusExceptionResponseError,
)
from ..modbus_core.heuristics import (
    check_fast_timeout,
    check_non_standard_port,
    check_silent_gateway,
    check_ghost_data,
    analyze_error_cause,
    analyze_connection_error,
)
from ..helpers.formatting import TraceLogger
from ..helpers.connection import get_client, get_config_entry

_LOGGER = logging.getLogger(__name__)


def _run_scan_sync(
    config_data,
    start_slave,
    end_slave,
    register,
    reg_type_code,
    timeout,
    retries,
    verbosity,
    log_to_file,
):
    """Synchronous scan execution."""

    trace = TraceLogger()

    # Verbosity Logic
    show_trace = verbosity in ["detailed", "debug"]
    show_debug = verbosity == "debug"

    # --- Unified Logger ---
    # Writes to:
    # 1. UI Trace (if show_trace/show_debug allows)
    # 2. File Log (if log_to_file is True OR level is warning/error)
    def log(msg, level="info"):
        # 1. Write to File?
        # Critical issues are ALWAYS logged to system log
        if log_to_file or level in ["warning", "error"]:
            if level == "error":
                _LOGGER.error(msg)
            elif level == "warning":
                _LOGGER.warning(msg)
            elif level == "debug":
                _LOGGER.debug(msg)
            else:
                _LOGGER.info(msg)

        # 2. Write to UI Trace?
        if level in ["error", "warning"] or show_trace:
            if level == "debug" and not show_debug:
                return  # Skip debug msg in detailed mode
            trace.log(msg)

    target = f"{config_data.get('host', 'Serial')}:{config_data.get('port', '')}"
    log(
        f"Starting scan on {config_data.get('name')} ({target}). Range {start_slave}-{end_slave}.",
        level="info",
    )

    # Heuristics: Static checks
    warn_fast = check_fast_timeout(timeout)
    if warn_fast:
        log(warn_fast, level="warning")

    warn_port = check_non_standard_port(
        config_data.get("port", 0), config_data.get("connection_type")
    )
    if warn_port:
        log(warn_port, level="warning")

    # Initialize Client
    client = get_client(config_data, timeout, retries)

    # Wire client packet logging to our logger
    # Only show packet logs in Debug mode
    if show_debug:
        client.trace_callback = lambda m: log(m, level="debug")

    found_devices = []
    scan_results = []  # Store raw results for analysis

    # Trackers for Heuristics
    error_count = 0
    ghost_count = 0

    try:
        try:
            client.connect()
        except Exception as e:
            hint = analyze_connection_error(e)
            if hint:
                log(f"Connection failed: {hint}", level="error")
                return {
                     "found_devices": [],
                     "trace": trace.get_trace(),
                     "count": 0,
                     "error": f"Connection Failed: {hint}"
                }
            raise e

        fc = reg_type_code
        req_data = struct.pack(">HH", register, 1)  # Read 1 register at 'register'

        for slave_id in range(start_slave, end_slave + 1):
            # Check for Late Responses from previous iterations
            while client._late_responses:
                lr = client._late_responses.pop(0)
                ghost_count += 1

                # Parse value from late response
                val = 0
                if len(lr.data) >= 3:
                    val = struct.unpack(">H", lr.data[1:3])[0]

                msg = f"Slave {lr.slave_id}: Found (Value {val}) (Late Recovery)"
                # Client already logged warning to system log, just add to UI trace
                trace.log(msg)
                scan_results.append(
                    {"slave_id": lr.slave_id, "status": "late_recovery"}
                )
                found_devices.append(
                    {"slave_id": lr.slave_id, "value": val, "note": "(Late Recovery)"}
                )

            try:
                start_req = time.monotonic()
                resp = client.execute(slave_id, fc, req_data)
                elapsed = time.monotonic() - start_req

                # If we got here, we have data.
                # Parse value (1 register = 2 bytes)
                # Modbus response (FC03/04) starts with Byte Count (1 byte)
                val = 0
                if len(resp) >= 3:
                    val = struct.unpack(">H", resp[1:3])[0]

                msg = f"Slave {slave_id}: Found (Value {val}) in {elapsed:.2f}s"
                log(msg, level="info")

                scan_results.append(
                    {"slave_id": slave_id, "status": "ok", "elapsed": elapsed}
                )
                found_devices.append(
                    {"slave_id": slave_id, "value": val, "elapsed": elapsed}
                )

            except ModbusExceptionResponseError as e:
                # Device exists but returned exception
                elapsed = time.monotonic() - start_req
                msg = f"Slave {slave_id}: Exception Response (Code {e.code}) in {elapsed:.2f}s"
                log(msg, level="warning")
                scan_results.append(
                    {
                        "slave_id": slave_id,
                        "status": "exception",
                        "error": str(e),
                        "elapsed": elapsed,
                    }
                )
                found_devices.append(
                    {
                        "slave_id": slave_id,
                        "error": f"Exception Code {e.code}",
                        "elapsed": elapsed,
                    }
                )

            except ModbusTimeoutError:
                # Timeout
                elapsed = time.monotonic() - start_req
                log(f"Slave {slave_id}: Timed out ({elapsed:.2f}s)", level="debug")
                scan_results.append(
                    {"slave_id": slave_id, "status": "timeout", "elapsed": elapsed}
                )
                error_count += 1

            except ModbusError as e:
                # Other error (CRC, Connection)
                elapsed = time.monotonic() - start_req
                # Client already logs ModbusError as warning if it happened in loop,
                # but here it might be a connection error from execute() outside loop.
                log(f"Slave {slave_id}: Error {e}", level="debug")
                scan_results.append(
                    {
                        "slave_id": slave_id,
                        "status": "error",
                        "error": str(e),
                        "elapsed": elapsed,
                    }
                )
                error_count += 1

        # Final check for Late Responses after loop
        while client._late_responses:
            lr = client._late_responses.pop(0)
            ghost_count += 1

            val = 0
            if len(lr.data) >= 3:
                val = struct.unpack(">H", lr.data[1:3])[0]

            msg = (
                f"Slave {lr.slave_id}: Found (Value {val}) (Late Recovery) - After Scan"
            )
            trace.log(msg)
            found_devices.append(
                {"slave_id": lr.slave_id, "value": val, "note": "(Late Recovery)"}
            )

    except Exception as e:
        log(f"Critical Scan Error: {e}", level="error")
    finally:
        client.close()

    # Heuristics: Post-Scan
    warn_silent = check_silent_gateway(
        len(found_devices), error_count, (end_slave - start_slave + 1)
    )
    if warn_silent:
        log(warn_silent, level="warning")

    warn_ghost = check_ghost_data(ghost_count, timeout)
    if warn_ghost:
        log(warn_ghost, level="warning")

    # Check Hard Timeouts
    hard_timeouts = [
        r
        for r in scan_results
        if r["status"] == "timeout" and r["elapsed"] >= (timeout * 0.95)
    ]
    if len(hard_timeouts) > 0 and len(found_devices) == 0:
        log(
            "Tip: Multiple hard timeouts detected. This may indicate the timeout is too short for the gateway.",
            level="warning",
        )

    # Info Summary
    total_scanned = end_slave - start_slave + 1
    total_found = len(found_devices)
    # duration is calculated outside in async wrapper, but we can't access it here easily for logging inside _run.
    # We'll just log scanned/found here.
    log(f"Scan Complete. Scanned: {total_scanned}, Found: {total_found}.", level="info")
    
    if total_found == 0 and error_count > 0:
        # No devices found, but errors occurred. Give a hint.
        # Use a generic error for analysis or try to capture the last error type?
        # We can use a generic ModbusTimeoutError if we saw timeouts, 
        # or just specific advice if we saw exceptions.
        # Simple approach: If timeouts > 0, check Timeout.
        hint = ""
        has_timeout = any(r['status'] == 'timeout' for r in scan_results)
        if has_timeout:
             hint = analyze_error_cause(ModbusTimeoutError("Scan Timeouts"))
        
        if hint:
             log(f"Hint: {hint}", level="warning")

    return {
        "found_devices": sorted(found_devices, key=lambda x: x.get("slave_id", 0)),
        "trace": trace.get_trace(),
        "count": len(found_devices),
    }


def _run_smart_scan(
    config_data,
    start_slave,
    end_slave,
    register,
    reg_type_code,
    timeout,
    retries,
    verbosity,
    log_to_file,
):
    """Smart Scan: Fire & Flush (Find First)."""
    trace = TraceLogger()
    show_trace = verbosity in ["detailed", "debug"]
    show_debug = verbosity == "debug"

    def log(msg, level="info"):
        if log_to_file or level in ["warning", "error"]:
            if level == "error":
                _LOGGER.error(msg)
            elif level == "warning":
                _LOGGER.warning(msg)
            elif level == "debug":
                _LOGGER.debug(msg)
            else:
                _LOGGER.info(msg)
        if level in ["error", "warning"] or show_trace:
            if level == "debug" and not show_debug:
                return
            trace.log(msg)

    target = f"{config_data.get('host', 'Serial')}:{config_data.get('port', '')}"
    log(f"Starting SMART Scan (Fire & Flush) on {target}. Range {start_slave}-{end_slave}.", level="info")

    client = get_client(config_data, timeout, retries)
    if show_debug:
        client.trace_callback = lambda m: log(m, level="debug")

    found_devices = []
    
    try:
        try:
            client.connect()
        except Exception as e:
            hint = analyze_connection_error(e)
            if hint:
                log(f"Connection failed: {hint}", level="error")
                return {"found_devices": [], "trace": trace.get_trace(), "error": f"Connection Failed: {hint}"}
            raise e

        req_data = struct.pack(">HH", register, 1)
        confirmed_id = None

        # Phase 1: Fire & Listen
        log("Phase 1: Rapid Fire...", level="info")
        
        for slave_id in range(start_slave, end_slave + 1):
            if confirmed_id is not None:
                break
            
            # Send (Non-blocking)
            client.send_raw_request(slave_id, reg_type_code, req_data)
            
            # Quick Peek (5ms)
            # If a device is fast, we catch it here.
            # If not, we catch it in a future iteration or the tail wait.
            try:
                resp = client.recv_raw_response(0.005)
                if resp:
                    resp_id, _, _, _ = resp
                    log(f"Activity detected on Slave {resp_id}!", level="warning")
                    confirmed_id = resp_id
                    break
            except Exception:
                pass # Ignore errors during scan phase

        # Phase 2: Tail Wait
        if confirmed_id is None:
            log("Phase 2: Waiting for stragglers...", level="info")
            start_wait = time.perf_counter()
            # Wait for 1x timeout period to catch any stragglers
            while (time.perf_counter() - start_wait) < timeout:
                try:
                    resp = client.recv_raw_response(0.1) # Check every 100ms
                    if resp:
                        resp_id, _, _, _ = resp
                        log(f"Activity detected on Slave {resp_id} (Tail)!", level="warning")
                        confirmed_id = resp_id
                        break
                except Exception:
                    pass

        # Phase 3: Verify & Flush
        if confirmed_id is not None:
            log(f"Phase 3: Verifying Slave {confirmed_id} with Standard Request...", level="info")
            # This calls execute(), which uses smart_drain to clear the buffer of any 
            # other responses we triggered, ensuring a clean sync.
            try:
                # We need to use the method arguments properly
                resp = client.execute(confirmed_id, reg_type_code, req_data)
                
                # Parse value
                val = 0
                if len(resp) >= 3:
                     val = struct.unpack(">H", resp[1:3])[0]
                
                log(f"Slave {confirmed_id} CONFIRMED! Value: {val}", level="info")
                found_devices.append({"slave_id": confirmed_id, "value": val, "note": "Smart Scan"})
            except Exception as e:
                log(f"Verification failed for {confirmed_id}: {e}", level="warning")
        else:
            log("No active devices found.", level="info")

    except Exception as e:
        log(f"Critical Scan Error: {e}", level="error")
    finally:
        client.close()

    return {
        "found_devices": found_devices,
        "trace": trace.get_trace(),
        "count": len(found_devices),
    }



async def scan_devices(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """Handle the scan_devices service."""
    hub_id = call.data.get("hub_id")
    entry = get_config_entry(hass, hub_id)

    start_slave = call.data.get("start_slave", 1)
    end_slave = call.data.get("end_slave", 10)
    register = call.data.get("register", 0)
    register_type = call.data.get("register_type", "holding")
    timeout = float(call.data.get("timeout", 2.0))
    retries = int(call.data.get("retries", 0))
    verbosity = call.data.get("verbosity", "basic")
    log_to_file = call.data.get("log_to_file", False)
    scan_mode = call.data.get("scan_mode", "standard")

    reg_type_code = 3 if register_type == "holding" else 4

    start_time = time.perf_counter()

    target_func = _run_smart_scan if scan_mode == "smart" else _run_scan_sync

    result = await hass.async_add_executor_job(
        target_func,
        entry.data,
        start_slave,
        end_slave,
        register,
        reg_type_code,
        timeout,
        retries,
        verbosity,
        log_to_file,
    )

    duration = time.perf_counter() - start_time
    result["scan_duration"] = duration
    result["scanned_range"] = f"{start_slave}-{end_slave}"
    result["mode"] = scan_mode

    return result
