"""Stress Test Action."""
import time
import struct
import logging
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse
from homeassistant.exceptions import ServiceValidationError

from ..modbus_core.client import SyncModbusClient
from ..modbus_core.exceptions import ModbusError, ModbusTimeoutError
from ..helpers.formatting import TraceLogger
from ..const import CONNECTION_TYPE_TCP, CONNECTION_TYPE_SERIAL

_LOGGER = logging.getLogger(__name__)

def _get_config_entry(hass: HomeAssistant, entry_id: str):
    entry = hass.config_entries.async_get_entry(entry_id)
    if not entry:
        raise ServiceValidationError(f"Hub {entry_id} not found.")
    return entry

def _run_stress_sync(config_data, unit_id, register, count, reg_type_code, iterations, timeout, retries):
    trace = TraceLogger()
    target = f"{config_data.get('host', 'Serial')}:{config_data.get('port', '')}"
    trace.log(f"Starting Stress Test on {config_data.get('name')} ({target})")
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
    success_count = 0
    timeout_count = 0
    error_count = 0
    latencies = []
    req_data = struct.pack(">HH", register, count)
    try:
        client.connect()
        for i in range(iterations):
            start_time = time.monotonic()
            try:
                client.execute(unit_id, reg_type_code, req_data)
                latency = time.monotonic() - start_time
                latencies.append(latency)
                success_count += 1
            except ModbusTimeoutError:
                timeout_count += 1
            except ModbusError:
                error_count += 1
            except Exception as e:
                trace.log(f"Critical error during iteration {i+1}: {e}")
                break
    except Exception as e:
        trace.log(f"Failed to initialize stress test: {e}")
    finally:
        client.close()
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    success_rate = (success_count / iterations) * 100 if iterations > 0 else 0
    trace.log(f"Completed {iterations} iterations.")
    trace.log(f"Success Rate: {success_rate:.1f}% ({success_count}/{iterations})")
    return {
        "success_rate": success_rate,
        "success_count": success_count,
        "timeout_count": timeout_count,
        "error_count": error_count,
        "avg_latency": avg_latency,
        "trace": trace.get_trace()
    }

async def stress_test(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    hub_id = call.data.get("hub_id")
    entry = _get_config_entry(hass, hub_id)
    unit_id = call.data.get("unit_id", 1)
    register = call.data.get("register", 0)
    count = call.data.get("count", 1)
    iterations = call.data.get("iterations", 50)
    register_type = call.data.get("register_type", "holding")
    timeout = float(call.data.get("timeout", 2.0))
    retries = int(call.data.get("retries", 0))
    reg_type_code = 3 if register_type == "holding" else 4
    return await hass.async_add_executor_job(_run_stress_sync, entry.data, unit_id, register, count, reg_type_code, iterations, timeout, retries)
