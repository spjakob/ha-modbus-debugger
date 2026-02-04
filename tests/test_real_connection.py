import pytest
import asyncio
from custom_components.modbus_debugger.modbus_core.client import SyncModbusClient
from custom_components.modbus_debugger.const import CONNECTION_TYPE_TCP


@pytest.mark.asyncio
async def test_real_connection_healthy(mock_modbus_server):
    """Test connecting to the local mock server (Unit 1: Healthy)."""
    port = mock_modbus_server
    client = SyncModbusClient(
        connection_type=CONNECTION_TYPE_TCP, host="127.0.0.1", port=port, timeout=0.5
    )

    loop = asyncio.get_running_loop()

    # Run synchronous client in executor
    def run_sync_logic():
        client.connect()
        # Read Unit 1, Register 0, Count 1 -> Expect 1111 (0x0457)
        # Result includes Byte Count (1 byte) + Data (2 bytes) = 3 bytes
        return client.execute(1, 3, b"\x00\x00\x00\x01")

    result = await loop.run_in_executor(None, run_sync_logic)

    assert len(result) == 3
    # First byte is byte count (2)
    assert result[0] == 2
    # Verify value is 1111 (set in mock_gateway.py)
    assert int.from_bytes(result[1:], "big") == 1111


@pytest.mark.asyncio
async def test_real_timeout_recovery(mock_modbus_server):
    """Test that the client correctly raises ModbusTimeoutError for Unit 3 (Timeout Profile)."""
    port = mock_modbus_server
    client = SyncModbusClient(
        connection_type=CONNECTION_TYPE_TCP,
        host="127.0.0.1",
        port=port,
        timeout=0.2,  # Short timeout, Mock takes 2.0s
    )

    loop = asyncio.get_running_loop()

    def run_fail_logic():
        from custom_components.modbus_debugger.modbus_core.exceptions import (
            ModbusTimeoutError,
        )

        client.connect()
        try:
            client.execute(3, 3, b"\x00\x00\x00\x01")
            return "missed"
        except ModbusTimeoutError:
            return "caught"
        finally:
            client.close()

    result = await loop.run_in_executor(None, run_fail_logic)
    assert result == "caught"
