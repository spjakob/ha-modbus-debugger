"""Scan Devices Action."""
import time
import logging
import struct
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

    # Heuristics
    warn_fast = check_fast_timeout(timeout)
    if warn_fast: trace.log(warn_fast)

    warn_port = check_non_standard_port(config_data.get('port', 0), config_data.get('connection_type'))
    if warn_port: trace.log(warn_port)

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
    scan_results = []
    error_count = 0

    try:
        client.connect()
        req_data = struct.pack(">HH", register, 1)

        for unit_id in range(start_unit, end_unit + 1):
            # Late Recovery
            while client._late_responses:
                lr = client._late_responses.pop(0)
                if show_trace: trace.log(f"Unit {lr.unit_id}: Late Recovery (Ghost Data)!")
                found_devices.append({"unit_id": lr.unit_id, "value": "Late Recovery"})

            try:
                start_req = time.monotonic()
                resp = client.execute(unit_id, reg_type_code, req_data)
                elapsed = time.monotonic() - start_req

                val = struct.unpack(">H", resp[:2])[0] if len(resp) >= 2 else 0
                if show_trace: trace.log(f"Unit {unit_id}: Found (Value {val})")

                scan_results.append({"unit_id": unit_id, "status": "ok", "elapsed": elapsed})
                found_devices.append({"unit_id": unit_id, "value": val, "elapsed": elapsed})

            except ModbusExceptionResponseError as e:
                elapsed = time.monotonic() - start_req
                if show_trace: trace.log(f"Unit {unit_id}: Exception Response (Code {e.code})")
                found_devices.append({"unit_id": unit_id, "error": f"Exception Code {e.code}", "elapsed": elapsed})

            except ModbusTimeoutError:
                elapsed = time.monotonic() - start_req
                if show_debug: trace.log(f"Unit {unit_id}: Timed out ({elapsed:.2f}s)")
                scan_results.append({"unit_id": unit_id, "status": "timeout", "elapsed": elapsed})
                error_count += 1

            except Exception as e:
                elapsed = time.monotonic() - start_req
                error_count += 1

        client.close()
    except Exception as e:
        trace.log(f"Critical Scan Error: {e}")

    return {
        "found_devices": sorted(found_devices, key=lambda x: x.get('unit_id', 0)),
        "trace": trace.get_trace(),
        "count": len(found_devices)
    }

async def scan_devices(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    hub_id = call.data.get("hub_id")
    entry = _get_config_entry(hass, hub_id)
    reg_type_code = 3 if call.data.get("register_type", "holding") == "holding" else 4

    return await hass.async_add_executor_job(
        _run_scan_sync, entry.data, call.data.get("start_unit", 1), call.data.get("end_unit", 10),
        call.data.get("register", 0), reg_type_code, float(call.data.get("timeout", 2.0)),
        int(call.data.get("retries", 0)), call.data.get("verbosity", "basic"), call.data.get("log_to_file", False)
    )
