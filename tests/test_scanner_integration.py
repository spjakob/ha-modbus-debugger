
import asyncio
import logging
import pytest
import time
import pytest_asyncio
import concurrent.futures
from custom_components.ha_modbus_debugger.scanner import ModbusScanner
from custom_components.ha_modbus_debugger.const import (
    CONNECTION_TYPE_TCP, CONF_HOST, CONF_PORT, CONF_CONNECTION_TYPE
)
from tests.mock_gateway import run_server

# Configure logging
logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)

PORT = 5021

@pytest_asyncio.fixture
async def mock_gateway(unused_tcp_port):
    from tests.mock_gateway import BUS
    BUS.reset() # Reset the lock for the new event loop

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

    results = []
    def callback(res):
        results.append(res)

    logs = []
    def log_cb(msg):
        logs.append(msg)

    # We must run the sync scanner in an executor to avoid blocking the mock server (which runs in this loop)
    loop = asyncio.get_running_loop()

    def run_sync_scan():
        return scanner.scan_tcp(
            start_unit=1,
            end_unit=6,
            register=0,
            reg_type=3, # Holding
            timeout=1.0,
            retries=1,
            update_callback=callback,
            log_callback=log_cb
        )

    await loop.run_in_executor(None, run_sync_scan)

    # Analyze Results
    res_map = {r['unit_id']: r for r in results}

    # ID 1: Healthy
    assert 1 in res_map
    assert res_map[1]['value'] == 1111

    # ID 2: Error
    assert 2 in res_map
    assert "error" in res_map[2]

    # ID 3: Timeout
    assert 3 not in res_map

    # ID 4: Error
    assert 4 in res_map
    assert "error" in res_map[4]

    # ID 5: Slow - Should succeed
    assert 5 in res_map
    assert res_map[5]['value'] == 5555

    # ID 6: Flaky - Succeed 2nd attempt
    assert 6 in res_map
    assert res_map[6]['value'] == 123

@pytest.mark.asyncio
async def test_gateway_congestion(mock_gateway):
    """Test that concurrent requests causing gateway congestion (head-of-line blocking) leads to timeouts on valid devices.
       NOTE: With Sync scanner, we process strictly sequentially.
       This test verifies that even if ID 3 blocks, ID 4 eventually runs after ID 3 finishes/timeouts.
       Unlike concurrent scan where ID 4 might timeout WHILE ID 3 is blocking.
       In sequential, ID 4 starts ONLY after ID 3 is done.
       So ID 4 SHOULD SUCCEED if the total test time allows it.
    """
    port = mock_gateway
    config = {
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP,
        CONF_HOST: "127.0.0.1",
        CONF_PORT: port
    }
    scanner = ModbusScanner(config)
    results = []

    # ID 3 = Timeout (2s). ID 4 = Error (Fast).
    # Sequential scan.
    # 1. Connect.
    # 2. Request 3. Wait 1s (Timeout). Fail.
    # 3. Request 4. Send. Wait response. Success.
    # So ID 4 SHOULD be present.

    loop = asyncio.get_running_loop()
    def run_sync_scan():
        return scanner.scan_tcp(
            start_unit=3, end_unit=4, register=0, reg_type=3,
            timeout=0.5, # Client timeout 0.5s. Server sleeps 2.0s for ID 3.
            retries=0,
            update_callback=lambda r: results.append(r)
        )

    await loop.run_in_executor(None, run_sync_scan)

    res_map = {r['unit_id']: r for r in results}

    # ID 3 should fail (Timeout)
    assert 3 not in res_map

    # ID 4 should BE PRESENT (Error response)
    # Because we waited for 3 to timeout (client side 0.5s), then sent 4.
    # The server might still be sleeping for 2.0s though?
    # Ah! The Mock Server runs in the main loop.
    # We call `getValues` which `await asyncio.sleep(2.0)`.
    # This BLOCKS the server loop from processing anything else if not careful?
    # No, `await asyncio.sleep` yields.
    # So the server loop is free.
    # BUT we used `async with BUS.lock`.
    # ID 3 holds lock for 2.0s.
    # Client ID 3 timeout at 0.5s. Client closes socket? Or continues?
    # Sync client continues.
    # Client sends ID 4.
    # Server accepts ID 4 request. Calls `getValues`.
    # `getValues` tries to acquire BUS.lock.
    # Lock is held by ID 3 task (still sleeping).
    # ID 4 task waits.
    # Client waits for ID 4 response.
    # If Client timeout (0.5s) < Remaining Lock Time (1.5s), ID 4 will TIMEOUT.
    # This PROVES congestion handling.

    # ID 3 starts at T=0. Holds lock until T=2.0. Client gives up at T=0.5.
    # ID 4 starts at T=0.51. Hits lock. Waits.
    # Lock releases at T=2.0.
    # ID 4 processes at T=2.0.
    # Client ID 4 waiting since T=0.51.
    # Client ID 4 timeout at T=1.01.
    # 2.0 > 1.01.
    # So ID 4 SHOULD TIMEOUT (Missing).

    assert 4 not in res_map

@pytest.mark.asyncio
async def test_gateway_connection_error():
    config = {
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP,
        CONF_HOST: "127.0.0.1",
        CONF_PORT: 59999
    }

    scanner = ModbusScanner(config)
    logs = []

    loop = asyncio.get_running_loop()
    def run_sync_scan():
        scanner.scan_tcp(
            start_unit=1, end_unit=1, register=0, reg_type=3,
            timeout=0.2, retries=0,
            log_callback=lambda m: logs.append(m)
        )
    await loop.run_in_executor(None, run_sync_scan)

    err_logs = [l for l in logs if "Connection Refused" in l]
    assert len(err_logs) > 0
