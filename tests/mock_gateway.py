
import asyncio
import logging
from pymodbus.server import StartAsyncTcpServer
from pymodbus.datastore import ModbusServerContext
from pymodbus.datastore import ModbusSequentialDataBlock
try:
    from pymodbus.datastore import ModbusSlaveContext
except ImportError:
    from pymodbus.datastore import ModbusDeviceContext as ModbusSlaveContext

from pymodbus.pdu import ExceptionResponse

_LOGGER = logging.getLogger(__name__)

# Shared "Bus" to simulate serialization delay using asyncio.Lock
# We need to initialize the lock lazily because the mock server might run in a different loop/thread context in tests?
# Pymodbus StartAsyncTcpServer runs in the current loop.
# The tests run in the current loop.
# But 'BUS = SharedBus()' creates the Lock at module level, potentially with the WRONG loop if created before test loop starts?
# Yes, asyncio.Lock() captures the *current* loop on init. If imported before test loop, it's bound to a closed or different loop.

class SharedBus:
    def __init__(self):
        self._lock = None

    @property
    def lock(self):
        # We need to ensure the lock is created on the *current* loop where it's accessed.
        # But a single Lock cannot cross loops.
        # The Mock Gateway runs in the same loop as the test in this setup?
        # Pytest-asyncio creates a new loop for each test function if loop_scope=function.
        # So BUS must be reset per test or use a contextvar?
        # Or simply, mock_gateway fixture should reset it.
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def reset(self):
        self._lock = None

BUS = SharedBus()

# Custom Contexts for behaviors
class MockSlaveContext(ModbusSlaveContext):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def async_getValues(self, fc, address, count=1):
        # Default behavior: Access BUS lock to simulate single wire
        async with BUS.lock:
            # Minimal bus time
            return super().getValues(fc, address, count)

class TimeoutContext(ModbusSlaveContext):
    async def async_getValues(self, fc, address, count=1):
        async with BUS.lock:
            # Hold the bus for 2.0s
            await asyncio.sleep(2.0)
            return super().getValues(fc, address, count)

class SlowContext(ModbusSlaveContext):
    async def async_getValues(self, fc, address, count=1):
        async with BUS.lock:
            await asyncio.sleep(0.2)
            return super().getValues(fc, address, count)

class ErrorContext(ModbusSlaveContext):
    async def async_getValues(self, fc, address, count=1):
        async with BUS.lock:
            # Return None to trigger server exception/empty response
            return None

class FlakyContext(ModbusSlaveContext):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.attempt = 0

    async def async_getValues(self, fc, address, count=1):
        async with BUS.lock:
            self.attempt += 1
            if self.attempt % 2 != 0:
                await asyncio.sleep(2.0)
            return super().getValues(fc, address, count)

async def run_server(port=5020):
    # ID 1: Healthy
    c1 = MockSlaveContext(hr=ModbusSequentialDataBlock(0, [1111]*100))

    # ID 2: Error (Illegal Address)
    c2 = ErrorContext(hr=ModbusSequentialDataBlock(0, [2222]*100))

    # ID 3: Timeout
    c3 = TimeoutContext(hr=ModbusSequentialDataBlock(0, [3333]*100))

    # ID 4: Gateway Error
    c4 = ErrorContext(hr=ModbusSequentialDataBlock(0, [4444]*100))

    # ID 5: Slow
    c5 = SlowContext(hr=ModbusSequentialDataBlock(0, [5555]*100))

    # ID 6: Flaky
    c6 = FlakyContext(hr=ModbusSequentialDataBlock(0, [123]*100))

    store = {
        1: c1,
        2: c2,
        3: c3,
        4: c4,
        5: c5,
        6: c6
    }

    context = ModbusServerContext(store, single=False)

    address = ("", port)
    server = await StartAsyncTcpServer(
        context=context,
        address=address,
    )
    return server

if __name__ == "__main__":
    asyncio.run(run_server())
