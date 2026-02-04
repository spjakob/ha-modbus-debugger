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
    """Get config entry by ID."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if not entry:
        raise ServiceValidationError(f"Hub {entry_id} not found.")
    return entry

def _run_stress_sync(config_data, unit_id, register, iterations, timeout):
    """Synchronous stress test execution."""
    trace = TraceLogger()

    trace.log(f"Starting Stress Test on {config_data.get('name')}. Iterations: {iterations}")

    client = SyncModbusClient(
        connection_type=config_data.get('connection_type'),
        host=config_data.get('host') if config_data.get('connection_type') == CONNECTION_TYPE_TCP else config_data.get('port'),
        port=config_data.get('port') if config_data.get('connection_type') == CONNECTION_TYPE_TCP else 0,
        timeout=timeout,
        retries=0, # Stress test usually shouldn't use internal retries to get accurate stats
        baudrate=config_data.get('baudrate', 9600),
        bytesize=config_data.get('bytesize', 8),
        parity=config_data.get('parity', 'N'),
        stopbits=config_data.get('stopbits', 1),
        rtu_over_tcp=config_data.get('rtu_over_tcp', False)
    )

    success_count = 0
    fail_count = 0
    latencies = []

    req_data = struct.pack(">HH", register, 1)

    try:
        client.connect()

        for i in range(iterations):
            start_time = time.monotonic()
            try:
                client.execute(unit_id, 3, req_data) # FC 03
                latency = time.monotonic() - start_time
                latencies.append(latency)
                success_count += 1
                if iterations <= 10: # Only log every iteration if few
                     trace.log(f"Iter {i+1}: Success ({latency:.3f}s)")
            except Exception as e:
                fail_count += 1
                trace.log(f"Iter {i+1}: Failed - {e}")

        client.close()

    except Exception as e:
        trace.log(f"Critical Stress Test Error: {e}")
    finally:
        client.close()

    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    success_rate = (success_count / iterations) * 100 if iterations > 0 else 0

    trace.log(f"Stress Test Finished. Success Rate: {success_rate:.1f}%. Avg Latency: {avg_latency:.3f}s")

    return {
        "success_rate": success_rate,
        "success_count": success_count,
        "fail_count": fail_count,
        "avg_latency": avg_latency,
        "trace": trace.get_trace()
    }

async def stress_test(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """Handle the stress_test_device service."""
    hub_id = call.data.get("hub_id")
    entry = _get_config_entry(hass, hub_id)

    unit_id = call.data.get("unit_id", 1)
    register = call.data.get("register", 0)
    iterations = call.data.get("iterations", 10)
    timeout = float(call.data.get("timeout", 2.0))

    return await hass.async_add_executor_job(
        _run_stress_sync,
        entry.data,
        unit_id,
        register,
        iterations,
        timeout
    )
