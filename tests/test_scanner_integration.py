
import asyncio, pytest, pytest_asyncio
from custom_components.ha_modbus_debugger.modbus_core.client import SyncModbusClient
from custom_components.ha_modbus_debugger.const import CONNECTION_TYPE_TCP
from tests.mock_gateway import run_server
@pytest_asyncio.fixture
async def mock_gateway(unused_tcp_port):
    from tests.mock_gateway import BUS
    BUS.reset(); port = unused_tcp_port
    task = asyncio.create_task(run_server(port))
    for i in range(20):
        try:
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.close(); await w.wait_closed(); break
        except: await asyncio.sleep(0.1)
    yield port
    task.cancel()
@pytest.mark.asyncio
async def test_persistent_connection(mock_gateway):
    client = SyncModbusClient(connection_type=CONNECTION_TYPE_TCP, host="127.0.0.1", port=mock_gateway, timeout=0.5)
    from unittest.mock import patch
    import socket as real_socket
    connection_count = 0
    real_create_conn = real_socket.create_connection
    def side_effect(*args, **kwargs):
        nonlocal connection_count
        if args[0][0] == "127.0.0.1": connection_count += 1
        return real_create_conn(*args, **kwargs)
    with patch("custom_components.ha_modbus_debugger.modbus_core.client.socket.create_connection", side_effect=side_effect):
        await asyncio.get_running_loop().run_in_executor(None, lambda: (client.connect(), client.execute(1, 3, bytes.fromhex("00000001")), client.execute(2, 3, bytes.fromhex("00000001")), client.close()))
        assert connection_count == 1
