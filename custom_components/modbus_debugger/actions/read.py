"""Read Register Action."""

import logging
import struct
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse

from ..modbus_core.exceptions import ModbusError
from ..modbus_core.heuristics import check_non_standard_port
from ..helpers.formatting import TraceLogger, TableFormatter
from ..helpers.connection import get_client, get_config_entry

_LOGGER = logging.getLogger(__name__)


def _run_read_sync(
    config_data,
    unit_id,
    register,
    count,
    reg_type_code,
    data_type_filter,
    timeout,
    retries,
):
    """Synchronous read execution."""
    trace = TraceLogger()

    target = f"{config_data.get('host', 'Serial')}:{config_data.get('port', '')}"
    trace.log(f"Target: {config_data.get('name')} ({target})")

    warn_port = check_non_standard_port(
        config_data.get("port", 0), config_data.get("connection_type")
    )
    if warn_port:
        trace.log(warn_port)

    client = get_client(config_data, timeout, retries)
    client.trace_callback = lambda msg: trace.log(
        msg
    )  # Always log packets to trace in Read mode

    all_registers = []

    try:
        client.connect()

        # Chunking Logic (Max 125 registers per request)
        MAX_CHUNK = 125
        remaining_count = count
        current_addr = register

        while remaining_count > 0:
            chunk_size = min(remaining_count, MAX_CHUNK)
            trace.log(f"Reading {chunk_size} registers from {current_addr}...")

            req_data = struct.pack(">HH", current_addr, chunk_size)

            try:
                resp = client.execute(unit_id, reg_type_code, req_data)

                # Response to Read Holding (03) / Input (04) starts with Byte Count (1 byte)
                if len(resp) < 1:
                    raise ModbusError("Empty response")

                byte_count = resp[0]
                data_bytes = resp[1:]

                if len(data_bytes) != byte_count:
                    trace.log(
                        f"Warning: Byte count mismatch. Expected {byte_count}, got {len(data_bytes)}"
                    )

                # Convert bytes to list of 16-bit integers
                num_regs = len(data_bytes) // 2

                for i in range(num_regs):
                    val = struct.unpack(">H", data_bytes[i * 2 : (i + 1) * 2])[0]
                    all_registers.append(val)

                current_addr += chunk_size
                remaining_count -= chunk_size

            except ModbusError as e:
                trace.log(f"Read failed at address {current_addr}: {e}")
                return {"error": str(e), "trace": trace.get_trace()}

        trace.log(f"Success. Received {len(all_registers)} registers.")

        # Format Table
        table = TableFormatter.format_read_result(
            all_registers, register, data_type_filter
        )

        return {
            "debug_info": f"Read {len(all_registers)} registers from Unit {unit_id}, Address {register}. Success.",
            "table": table,
            "trace": trace.get_trace(),
        }

    except Exception as e:
        _LOGGER.error("Critical Error during read: %s", e)
        trace.log(f"Critical Error: {e}")
        return {"error": str(e), "trace": trace.get_trace()}
    finally:
        client.close()


async def read_register(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """Handle the read_register service."""
    hub_id = call.data.get("hub_id")
    entry = get_config_entry(hass, hub_id)

    unit_id = call.data.get("unit_id", 1)
    register = call.data.get("register")
    count = call.data.get("count", 1)
    register_type = call.data.get("register_type", "holding")
    data_type_filter = call.data.get("data_type", "all")
    timeout = float(call.data.get("timeout", 2.0))
    retries = int(call.data.get("retries", 0))

    reg_type_code = 3 if register_type == "holding" else 4

    return await hass.async_add_executor_job(
        _run_read_sync,
        entry.data,
        unit_id,
        register,
        count,
        reg_type_code,
        data_type_filter,
        timeout,
        retries,
    )
