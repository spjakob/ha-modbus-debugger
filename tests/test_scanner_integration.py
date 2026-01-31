
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

# Configure logging
logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)

PORT = 5021

# We use a session-scoped fixture or robust cleanup to avoid "Address already in use"
# But pytest-asyncio strict mode makes session-scoped async fixtures tricky with event loops.
# Let's ensure strict cleanup or use dynamic ports.
# Dynamic port is safer.

@pytest_asyncio.fixture
async def mock_gateway(unused_tcp_port):
    port = unused_tcp_port
    task = asyncio.create_task(run_server(port))

    # Wait for start
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
async def test_scanner_scenarios(mock_gateway):
    port = mock_gateway
    config = {
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP,
        CONF_HOST: "127.0.0.1",
        CONF_PORT: port
    }

    scanner = ModbusScanner(config)

    # We scan IDs 1-6
    # Profile: Timeout 1.0s, Retries 1 (Total 2 attempts), Concurrency 1 (Sequential for stability/tracing)

    results = []
    def callback(res):
        results.append(res)

    logs = []
    def log_cb(msg):
        logs.append(msg)

    await scanner.scan_tcp(
        start_unit=1,
        end_unit=6,
        register=0,
        reg_type=3, # Holding
        timeout=1.0,
        retries=1,
        concurrency=1,
        update_callback=callback,
        log_callback=log_cb
    )

    # Analyze Results
    res_map = {r['unit_id']: r for r in results}

    # ID 1: Healthy
    assert 1 in res_map
    assert res_map[1]['value'] == 1111

    # ID 2: Error
    # Our Mock Gateway returns empty response/None for error contexts
    assert 2 in res_map
    assert "error" in res_map[2]

    # ID 3: Timeout (Sleep 2s vs Timeout 1s)
    # Should NOT be in results (Missing Device)
    assert 3 not in res_map

    # Check that logging captured the timeout with the new format
    # "Unit 3: Timeout (1.XXs)"
    timeout_logs = [l for l in logs if "Unit 3: Timeout" in l]
    assert len(timeout_logs) > 0
    assert "(" in timeout_logs[0] and "s)" in timeout_logs[0]

    # ID 4: Error
    assert 4 in res_map
    assert "error" in res_map[4]

    # ID 5: Slow (Sleep 0.2s vs Timeout 1s) - Should succeed
    assert 5 in res_map
    assert res_map[5]['value'] == 5555
    # Verify timing log
    response_logs = [l for l in logs if "Unit 5: Response (" in l]
    assert len(response_logs) > 0

    # ID 6: Flaky (Fail 1st, Succeed 2nd)
    # Since we have retries=1, it should succeed on 2nd attempt.
    assert 6 in res_map
    assert res_map[6]['value'] == 123 # Default value

    # Check Logs for ID 6
    id6_logs = [l for l in logs if "Unit 6" in l]
    attempts = [l for l in id6_logs if "Attempt" in l]
    assert len(attempts) >= 2

@pytest.mark.asyncio
async def test_gateway_congestion(mock_gateway):
    """Test that concurrent requests causing gateway congestion (head-of-line blocking) leads to timeouts on valid devices."""
    port = mock_gateway
    config = {
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP,
        CONF_HOST: "127.0.0.1",
        CONF_PORT: port
    }
    scanner = ModbusScanner(config)
    results = []

    # ID 3 = Timeout (2s). ID 1 = Fast.
    # Scan 3 then 1 with Concurrency 2.
    # Request 3 sent. Block 2s.
    # Request 1 sent (parallel). Gateway is blocked by 3.
    # If Timeout < 2s, Request 1 will timeout waiting for Gateway.

    await scanner.scan_tcp(
        start_unit=3, end_unit=4, register=0, reg_type=3,
        timeout=0.5, # Timeout less than ID 3 sleep
        retries=0,
        concurrency=2,
        update_callback=lambda r: results.append(r)
    )

    res_map = {r['unit_id']: r for r in results}

    # ID 3 should fail (Timeout)
    assert 3 not in res_map

    # ID 4 (Fast Error) should FAIL (Timeout) due to congestion caused by ID 3.
    # Ideally 4 should return "Error" (Device Present), but because 3 blocks the server, 4 times out.
    # So 4 should NOT be in results.
    assert 4 not in res_map

@pytest.mark.asyncio
async def test_gateway_connection_error():
    # Test connection to closed port
    config = {
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP,
        CONF_HOST: "127.0.0.1",
        CONF_PORT: 59999 # Unused port
    }

    scanner = ModbusScanner(config)

    logs = []
    await scanner.scan_tcp(
        start_unit=1, end_unit=1, register=0, reg_type=3,
        timeout=0.2, retries=0, concurrency=1,
        log_callback=lambda m: logs.append(m)
    )

    # Verify we logged the specific connection error
    err_logs = [l for l in logs if "Connection Refused" in l]
    assert len(err_logs) > 0
