
import asyncio
import logging
import pytest
import time
import pytest_asyncio
from custom_components.ha_modbus_debugger.scanner import ModbusScanner
from custom_components.ha_modbus_debugger.const import (
    CONNECTION_TYPE_TCP, CONF_HOST, CONF_PORT, CONF_CONNECTION_TYPE
)
from tests.mock_gateway import run_server

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)

PORT = 5022 # Use different port to avoid conflicts if needed

@pytest_asyncio.fixture
async def mock_gateway(unused_tcp_port):
    from tests.mock_gateway import BUS
    BUS.reset()
    port = unused_tcp_port
    task = asyncio.create_task(run_server(port))

    for i in range(20):
        try:
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.close()
            await w.wait_closed()
            break
        except (OSError, asyncio.TimeoutError):
            await asyncio.sleep(0.1)
    else:
        pytest.fail("Mock Gateway failed to start")

    yield port

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

@pytest.mark.asyncio
async def test_persistent_connection(mock_gateway):
    """Test that the scanner uses a single persistent connection."""
    port = mock_gateway
    config = {
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP,
        CONF_HOST: "127.0.0.1",
        CONF_PORT: port
    }
    scanner = ModbusScanner(config)

    from unittest.mock import MagicMock, patch
    import socket as real_socket

    connection_count = 0
    real_create_conn = real_socket.create_connection

    def side_effect(*args, **kwargs):
        nonlocal connection_count
        connection_count += 1
        return real_create_conn(*args, **kwargs)

    # Patch where it is IMPORTED in scanner.py?
    # scanner.py imports socket. So we patch scanner.socket.create_connection
    # OR we patch socket.create_connection globally if safe?
    # Let's try patching custom_components.ha_modbus_debugger.scanner.socket.create_connection again,
    # but make sure we import it correctly in the test file to patch?
    # No, patch string path is correct.
    # The issue might be that scanner.py does `import socket` and calls `socket.create_connection`.
    # `with patch("custom_components.ha_modbus_debugger.scanner.socket.create_connection", side_effect=side_effect)` should work.

    # Wait, previous failure was "assert 0 == 1". So connection_count was 0.
    # This implies the side_effect was NOT called.
    # OR the mock server failed?
    # If mock server failed, scan_tcp returns early?
    # scan_tcp catches exceptions.

    # Let's verify logs to see if it connected.
    logs = []

    with patch("custom_components.ha_modbus_debugger.scanner.socket.create_connection", side_effect=side_effect) as mock_create:

        loop = asyncio.get_running_loop()
        def run_scan():
            return scanner.scan_tcp(
                start_unit=1, end_unit=5, register=0, reg_type=3,
                timeout=0.5, retries=0,
                log_callback=lambda m: logs.append(m)
            )

        await loop.run_in_executor(None, run_scan)

        # Check if connected
        connected_logs = [l for l in logs if "Connected" in l]
        assert len(connected_logs) > 0

        # Assert connection count
        # If patch worked, connection_count should be > 0
        assert connection_count == 1

@pytest.mark.asyncio
async def test_ghost_data_detection(mock_gateway):
    """Test detection of ghost data (unexpected data on socket before send)."""
    port = mock_gateway
    config = {
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP,
        CONF_HOST: "127.0.0.1",
        CONF_PORT: port
    }
    scanner = ModbusScanner(config)

    logs = []
    def log_cb(msg):
        logs.append(msg)

    from unittest.mock import MagicMock, patch

    mock_sock = MagicMock()

    select_results = [
        ([], [], []),
        ([mock_sock], [], []),
        ([], [], [])
    ]

    def mock_select(*args):
        if select_results:
             return select_results.pop(0)
        return ([], [], [])

    recv_side_effects = [
        bytes.fromhex("00010000000501"),
        bytes.fromhex("03020457"),
        bytes.fromhex("DEADBEEF"),
        bytes.fromhex("00020000000502"),
        bytes.fromhex("03020457"),
    ]

    def mock_recv(n):
        if not recv_side_effects:
             return b''
        return recv_side_effects.pop(0)

    mock_sock.recv = MagicMock(side_effect=mock_recv)

    with patch("custom_components.ha_modbus_debugger.scanner.socket.create_connection", return_value=mock_sock), \
         patch("custom_components.ha_modbus_debugger.scanner.select.select", side_effect=mock_select):

         loop = asyncio.get_running_loop()
         def run_scan():
             # Scan 2 units
             return scanner.scan_tcp(
                 start_unit=1, end_unit=2, register=0, reg_type=3,
                 timeout=1.0, retries=0,
                 log_callback=log_cb
             )

         await loop.run_in_executor(None, run_scan)

         ghost_logs = [l for l in logs if "WARNING - Ghost data cleared" in l]
         assert len(ghost_logs) == 1
         assert "deadbeef" in ghost_logs[0].lower()
