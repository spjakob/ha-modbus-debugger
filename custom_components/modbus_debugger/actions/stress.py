"""Stress Test Action."""

import time
import struct
import logging
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse
from ..modbus_core.exceptions import ModbusError, ModbusTimeoutError
from ..helpers.formatting import TraceLogger
from ..helpers.connection import get_client, get_config_entry

_LOGGER = logging.getLogger(__name__)


def _run_stress_sync(
    config_data, unit_id, register, count, reg_type_code, iterations, timeout, retries
):
    trace = TraceLogger()
    target = f"{config_data.get('host', 'Serial')}:{config_data.get('port', '')}"
    trace.log(f"Starting Stress Test on {config_data.get('name')} ({target})")

    client = get_client(config_data, timeout, retries)
    success_count = 0
    timeout_count = 0
    error_count = 0
    latencies = []
    MAX_CHUNK = 125

    try:
        client.connect()
        for i in range(iterations):
            start_time = time.monotonic()
            remaining = count
            current_addr = register
            try:
                while remaining > 0:
                    chunk_size = min(remaining, MAX_CHUNK)
                    req_data = struct.pack(">HH", current_addr, chunk_size)
                    client.execute(unit_id, reg_type_code, req_data)
                    remaining -= chunk_size
                    current_addr += chunk_size

                latency = time.monotonic() - start_time
                latencies.append(latency)
                success_count += 1
            except ModbusTimeoutError:
                timeout_count += 1
            except ModbusError:
                error_count += 1
            except Exception as e:
                _LOGGER.error(
                    "Critical error during stress test iteration %d: %s", i + 1, e
                )
                trace.log(f"Critical error iteration {i + 1}: {e}")
                break
    except Exception as e:
        _LOGGER.error("Failed to initialize stress test: %s", e)
        trace.log(f"Failed to initialize: {e}")
    finally:
        client.close()

    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    success_rate = (success_count / iterations) * 100 if iterations > 0 else 0
    trace.log(f"Completed {iterations} iterations. Success: {success_rate:.1f}%")

    return {
        "success_rate": success_rate,
        "success_count": success_count,
        "timeout_count": timeout_count,
        "error_count": error_count,
        "avg_latency": avg_latency,
        "trace": trace.get_trace(),
    }


async def stress_test(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    hub_id = call.data.get("hub_id")
    entry = get_config_entry(hass, hub_id)
    return await hass.async_add_executor_job(
        _run_stress_sync,
        entry.data,
        call.data.get("unit_id", 1),
        call.data.get("register", 0),
        call.data.get("count", 1),
        3 if call.data.get("register_type", "holding") == "holding" else 4,
        call.data.get("iterations", 50),
        float(call.data.get("timeout", 2.0)),
        int(call.data.get("retries", 0)),
    )
