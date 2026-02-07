"""Stress Test Action (Latency measurement, Throughput, Caching checks)."""


import time
import struct
import logging
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse
from homeassistant.exceptions import ServiceValidationError
from ..modbus_core.exceptions import ModbusError, ModbusTimeoutError
from ..modbus_core.heuristics import check_fast_response
from ..helpers.formatting import TraceLogger
from ..helpers.connection import get_client, get_config_entry

_LOGGER = logging.getLogger(__name__)


def _run_stress_sync(
    config_data, slave_id, register, count, reg_type_code, iterations, timeout, retries, verbosity, alternate
):
    trace = TraceLogger()
    target = f"{config_data.get('host', 'Serial')}:{config_data.get('port', '')}"
    
    start_time_global = time.perf_counter()
    start_msg = f"Starting Stress Test on {config_data.get('name')} ({target})"
    trace.log(start_msg)
    _LOGGER.info(start_msg)

    client = get_client(config_data, timeout, retries)
    
    # Wire trace callback based on verbosity
    # Basic: No client trace
    # Detailed: Log connection/errors (filter out TX/RX)
    # Debug: Log everything
    if verbosity in ['detailed', 'debug']:
        def scoped_callback(msg):
            is_packet = msg.startswith("TX:") or msg.startswith("RX:")
            if verbosity == 'detailed' and is_packet:
                return # Skip packets in detailed mode
            trace.log(msg)
            
        client.trace_callback = scoped_callback
    success_count = 0
    timeout_count = 0
    error_count = 0
    latencies = []
    MAX_CHUNK = 125
    total_bytes = 0

    try:
        client.connect()
        # Initial connection check?
        
        for i in range(iterations):
            iter_start = time.perf_counter()
            
            # Check for Late Responses (Ghost Data)
            while client._late_responses:
                lr = client._late_responses.pop(0)
                if verbosity == 'debug':
                     trace.log(f"Slave {lr.slave_id}: Late Recovery (Ghost Data)!")

            remaining = count
            current_addr = register
            # Alternating Logic: If enabled, toggle between register and register+1
            if alternate and (i % 2 == 1):
                current_addr = register + 1

            iter_bytes = 0
            
            try:
                while remaining > 0:
                    chunk_size = min(remaining, MAX_CHUNK)
                    req_data = struct.pack(">HH", current_addr, chunk_size)
                    
                    # Execute Modbus Request
                    # For throughput, we should count actual bytes transferred on wire.
                    # PDU Request: 1 (FC) + 2 (Addr) + 2 (Count) = 5 bytes
                    # MBAP/RTU Overhead: 
                    #   TCP: 7 bytes Header
                    #   RTU: 1 byte Unit + 2 bytes CRC = 3 bytes
                    # PDU Response (Read): 1 (FC) + 1 (ByteCount) + N*2 (Data)
                    
                    resp = client.execute(slave_id, reg_type_code, req_data)
                    
                    # Approximate PDU bytes
                    iter_bytes += 5 # Request PDU
                    iter_bytes += (2 + len(resp)) # Response PDU (FC+ByteCount+Data)
                    # Add Transport Overhead (approx)
                    # Assuming TCP for 'host', Serial otherwise?
                    if 'host' in config_data: # TCP
                        iter_bytes += (7 + 7) # Header both ways
                    else: # RTU
                        iter_bytes += (3 + 3) # Addr+CRC both ways

                    remaining -= chunk_size
                    current_addr += chunk_size

                latency = time.perf_counter() - iter_start
                latencies.append(latency)
                success_count += 1
                total_bytes += iter_bytes
                
                if verbosity == 'debug':
                     trace.log(f"Iter {i+1}: Success ({latency*1000:.2f}ms)")
                     
            except ModbusTimeoutError:
                timeout_count += 1
                trace.log(f"Iter {i+1}: Timeout")
                _LOGGER.warning(f"Stress test timeout on iter {i+1}")
            except ModbusError as e:
                error_count += 1
                trace.log(f"Iter {i+1}: Error: {e}")
                _LOGGER.warning(f"Stress test error on iter {i+1}: {e}")
            except Exception as e:
                _LOGGER.error(
                    "Critical error during stress test iteration %d: %s", i + 1, e
                )
                trace.log(f"Critical error iteration {i + 1}: {e}")
                error_count += 1 # Count as error
                # break? User might want to continue...
                
    except Exception as e:
        _LOGGER.error("Failed to initialize stress test: %s", e)
        trace.log(f"Failed to initialize: {e}")
    finally:
        client.close()

    end_time_global = time.perf_counter()
    total_duration = end_time_global - start_time_global
    
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    success_rate = (success_count / iterations) * 100 if iterations > 0 else 0
    throughput_bps = (total_bytes * 8) / total_duration if total_duration > 0 else 0

    completion_msg = (
        f"Completed {iterations} iterations in {total_duration:.2f}s. "
        f"Success: {success_rate:.1f}%"
    )
    
    # Heuristics
    fast_warn = check_fast_response(avg_latency * 1000)
    if fast_warn:
         trace.log(fast_warn)
         _LOGGER.warning(fast_warn)

    trace.log(completion_msg)
    _LOGGER.info(completion_msg)

    return {
        "success_rate": success_rate,
        "success_count": success_count,
        "timeout_count": timeout_count,
        "error_count": error_count,
        "avg_latency_ms": avg_latency * 1000, # Convert to ms
        "total_duration_s": total_duration,
        "throughput_bps": throughput_bps,
        "trace": trace.get_trace(),
    }


async def stress_test(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    hub_id = call.data.get("hub_id")
    entry = get_config_entry(hass, hub_id)
    return await hass.async_add_executor_job(
        _run_stress_sync,
        entry.data,
        call.data.get("slave_id", 1),
        call.data.get("register", 0),
        call.data.get("count", 1),
        3 if call.data.get("register_type", "holding") == "holding" else 4,
        int(call.data.get("iterations", 50)),
        float(call.data.get("timeout", 2.0)),
        int(call.data.get("retries", 0)),
        call.data.get("verbosity", "basic"),
        call.data.get("alternate", False),
    )
