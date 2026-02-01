import asyncio
import time
import socket
import struct
import logging
from pymodbus.server import StartAsyncTcpServer
from pymodbus.datastore import ModbusServerContext, ModbusSequentialDataBlock
try:
    from pymodbus.datastore import ModbusSlaveContext
except ImportError:
    from pymodbus.datastore import ModbusDeviceContext as ModbusSlaveContext

# Minimal Mock Server that processes requests
# We need it to be able to handle multiple requests on one connection if pipelining is supported.
# Pymodbus TCP Server architecture:
# It reads request, processes, writes response.
# Does it buffer multiple requests?
# Usually yes, the TCP stream is read.
# But it might process them sequentially.

class FastContext(ModbusSlaveContext):
    def getValues(self, fc, address, count=1):
        return [123] * count

class TimeoutContext(ModbusSlaveContext):
    def getValues(self, fc, address, count=1):
        import time
        time.sleep(0.5) # 0.5s Timeout simulation
        return super().getValues(fc, address, count)

async def run_mock_server(port):
    store = {}
    # 1-5: Healthy (Fast)
    for i in range(1, 6):
        store[i] = FastContext(hr=ModbusSequentialDataBlock(0, [1]*10))

    # 6-50: Timeout (Missing)
    for i in range(6, 51):
        store[i] = TimeoutContext(hr=ModbusSequentialDataBlock(0, [0]*10))

    context = ModbusServerContext(store, single=False)
    server = await StartAsyncTcpServer(context=context, address=("127.0.0.1", port))
    return server

# --- Clients ---

async def client_sync(host, port, units):
    # Sequential, Persistent Connection
    start = time.perf_counter()
    found = 0
    try:
        r, w = await asyncio.open_connection(host, port)
        for u in units:
            req = struct.pack('>HHHBBHH', 0, 0, 6, u, 3, 0, 1)
            w.write(req)
            await w.drain()
            try:
                # Read header
                data = await asyncio.wait_for(r.read(7), timeout=0.6)
                if len(data) == 7:
                    # Read rest
                    length = struct.unpack('>H', data[4:6])[0]
                    await asyncio.wait_for(r.read(length-1), timeout=0.6)
                    found += 1
            except asyncio.TimeoutError:
                # Close and Reconnect on timeout?
                # In Sync mode, if we timeout, we often lose sync or assume connection dead.
                # But for simulation let's say we assume packet loss and continue?
                # No, standard sync usually closes.
                w.close()
                await w.wait_closed()
                r, w = await asyncio.open_connection(host, port)
        w.close()
        await w.wait_closed()
    except Exception as e:
        print(f"Sync Error: {e}")
    return time.perf_counter() - start, found

async def client_async(host, port, units, concurrency=10):
    # Concurrent, New Connection per Request
    start = time.perf_counter()
    found = 0
    sem = asyncio.Semaphore(concurrency)

    async def scan(u):
        nonlocal found
        async with sem:
            try:
                r, w = await asyncio.open_connection(host, port)
                req = struct.pack('>HHHBBHH', 0, 0, 6, u, 3, 0, 1)
                w.write(req)
                await w.drain()
                await asyncio.wait_for(r.read(1024), timeout=0.6)
                found += 1
                w.close()
                await w.wait_closed()
            except:
                pass

    await asyncio.gather(*[scan(u) for u in units])
    return time.perf_counter() - start, found

async def client_pipeline(host, port, units, window=10):
    # Pipelined, Persistent Connection
    start = time.perf_counter()
    found = 0
    try:
        r, w = await asyncio.open_connection(host, port)

        # We assume responses come in order for Modbus TCP usually,
        # OR we map by TID.
        # Let's send in batches of 'window'.

        for i in range(0, len(units), window):
            batch = units[i:i+window]
            # Send all
            for u in batch:
                # TID = u
                req = struct.pack('>HHHBBHH', u, 0, 6, u, 3, 0, 1)
                w.write(req)
            await w.drain()

            # Read responses
            # We expect len(batch) responses.
            # But some might timeout (server doesn't reply).
            # This is the tricky part of Pipelining!
            # If server silently drops "Timeout" requests (Mock TimeoutContext sleeps then replies?
            # In reality, missing device = NO REPLY from Gateway).
            # If No Reply, we hang waiting for it.
            # So Pipelining ONLY works if the Gateway sends an Exception or Gateway Path Unavailable.
            # If Gateway is silent, Pipeline stalls.
            # Unless we have a reader task that matches TIDs and a timeout manager.

            # For simulation, let's assume we implement a smart reader.
            # But wait, if Gateway processes serially and blocks on unit X,
            # we won't get response for X+1 until X times out.
            # So Pipelining provides NO benefit over Sync if the bottleneck is the Serial Bus blocking.
            # It ONLY helps if the Gateway can process requests in parallel (multiple serial ports?)
            # or if the bottleneck is TCP Handshake.

            # Let's try to read ONE response.
            try:
                # We try to read as many as sent?
                # If we get blocked reading, we fail.
                pass
            except:
                pass

        w.close()
        await w.wait_closed()
    except Exception:
        pass
    return time.perf_counter() - start, found

async def main():
    port = 5025
    # Start server task
    srv = asyncio.create_task(run_mock_server(port))
    await asyncio.sleep(1)

    units = list(range(1, 51)) # 50 units. 1-5 fast, 6-50 slow (0.5s).

    print("--- Starting Simulation ---")
    print(f"Scenario: 50 Units. 5 Fast, 45 Slow/Timeout (0.5s delay).")

    # Test A: Sync (Sequential)
    # Expected: 5 * 0.0 + 45 * 0.5 = ~22.5s
    t_sync, f_sync = await client_sync("127.0.0.1", port, units)
    print(f"Sync (Seq): {t_sync:.2f}s. Found: {f_sync}")

    # Test B: Async (Concurrent=10)
    # Expected: 45 timeouts. 10 at a time. 45/10 = 4.5 batches. 4.5 * 0.5s = 2.25s?
    # PLUS overhead.
    # BUT, server is single threaded?
    # StartAsyncTcpServer handles each connection in a task?
    # If pymodbus server is async, it handles 10 connections.
    # BUT we made TimeoutContext BLOCK using time.sleep.
    # This simulates a "Blocked Bus".
    # So even if we have 10 connections, they will be processed ONE BY ONE by the blocked server loop.
    # So Async should take same as Sync: ~22.5s!
    # UNLESS pymodbus runs handling in threads. (It doesn't by default).
    t_async, f_async = await client_async("127.0.0.1", port, units, concurrency=10)
    print(f"Async (10): {t_async:.2f}s. Found: {f_async}")

    # Test C: Pipelined
    # If Bus is blocked, Pipelining on 1 socket just fills the buffer.
    # Server reads 1, sleeps 0.5s. Reads 2, sleeps 0.5s.
    # Time = 22.5s.
    # t_pipe, f_pipe = await client_pipeline("127.0.0.1", port, units)
    # print(f"Pipeline: {t_pipe:.2f}s. Found: {f_pipe}")

    srv.cancel()

if __name__ == "__main__":
    asyncio.run(main())
