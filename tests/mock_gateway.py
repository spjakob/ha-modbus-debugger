
import asyncio
import logging
from pymodbus.server import StartAsyncTcpServer
from pymodbus.datastore import ModbusServerContext
# Pymodbus v3.x split context
from pymodbus.datastore import ModbusSequentialDataBlock
try:
    from pymodbus.datastore import ModbusSlaveContext
except ImportError:
    # v3.11+ might use DeviceContext? Or BaseDeviceContext
    # Actually in v3.11 it seems ModbusSlaveContext was renamed or moved?
    # Let's check 'context' submodule.
    # It is ModbusSlaveContext in v3.0, but output showed ModbusBaseDeviceContext, ModbusDeviceContext.
    # It seems ModbusSlaveContext is gone or renamed to ModbusDeviceContext?
    from pymodbus.datastore import ModbusDeviceContext as ModbusSlaveContext

# from pymodbus.device import ModbusDeviceIdentification # Not needed and might be moved
from pymodbus.pdu import ExceptionResponse

_LOGGER = logging.getLogger(__name__)

# Shared "Bus" to simulate serialization delay
class SharedBus:
    def __init__(self):
        self.lock = asyncio.Lock()

BUS = SharedBus()

# Custom Data Block to simulate different behaviors based on Unit ID
class MockSparseDataBlock(ModbusSequentialDataBlock):
    def __init__(self, unit_id):
        super().__init__(0, [0] * 100)
        self.unit_id = unit_id
        self.request_count = 0

    def getValues(self, address, count=1):
        """Return values with simulated behavior."""
        return [0] * count

class MockSlaveContext(ModbusSlaveContext):
    def __init__(self):
        super().__init__(
            di=ModbusSequentialDataBlock(0, [0]*100),
            co=ModbusSequentialDataBlock(0, [0]*100),
            hr=ModbusSequentialDataBlock(0, [0]*100),
            ir=ModbusSequentialDataBlock(0, [0]*100),
            zero_mode=True
        )
        self.id6_counter = 0

    # ModbusDeviceContext does not have 'validate' method.
    # It seems logic moved to Server or base context.
    # However, getValues is the main entry point for data.
    # If we want to simulate errors or delays, we should override getValues.
    # getValues returns data list OR Exception Code.

    def getValues(self, fc, address, count=1):
        return super().getValues(fc, address, count)

# Special Contexts for behaviors
class TimeoutContext(ModbusSlaveContext):
    def getValues(self, fc, address, count=1):
        import time
        # Simulate BUS blocking
        # We can't use await here easily because getValues might be sync in some backends,
        # but pymodbus AsyncTcpServer usually runs in executor or handles sync?
        # Actually StartAsyncTcpServer runs in loop.
        # If getValues is blocking (time.sleep), it BLOCKS THE LOOP.
        # This is EXACTLY what happens on a single-threaded server/gateway.
        time.sleep(2.0) # Blocking sleep to force client timeout AND block other requests
        return super().getValues(fc, address, count)

class SlowContext(ModbusSlaveContext):
    def getValues(self, fc, address, count=1):
        import time
        time.sleep(0.2) # Small delay
        return super().getValues(fc, address, count)

class ErrorContext(ModbusSlaveContext):
    def getValues(self, fc, address, count=1):
        return None # Should trigger error?

class FlakyContext(ModbusSlaveContext):
    def __init__(self):
        super().__init__(hr=ModbusSequentialDataBlock(0, [123]*100))
        self.attempt = 0

    def getValues(self, fc, address, count=1):
        self.attempt += 1
        if self.attempt % 2 != 0:
            import time
            time.sleep(2.0) # Timeout first
        return super().getValues(fc, address, count)

async def run_server(port=5020):
    # ID 1: Healthy
    c1 = ModbusSlaveContext(hr=ModbusSequentialDataBlock(0, [1111]*100))

    # ID 2: Error (Illegal Address)
    c2 = ErrorContext(hr=ModbusSequentialDataBlock(0, [2222]*100)) # validate returns False

    # ID 3: Timeout
    c3 = TimeoutContext(hr=ModbusSequentialDataBlock(0, [3333]*100))

    # ID 4: Gateway Error (Using ErrorContext for now as placeholder for 0x0B difficulty)
    # Getting strict 0x0B from standard pymodbus server is hard without patching.
    # We will accept 0x02 as "Error Response" for test purposes or mock packet level.
    c4 = ErrorContext(hr=ModbusSequentialDataBlock(0, [4444]*100))

    # ID 5: Slow
    c5 = SlowContext(hr=ModbusSequentialDataBlock(0, [5555]*100))

    # ID 6: Flaky
    c6 = FlakyContext()

    store = {
        1: c1,
        2: c2,
        3: c3,
        4: c4,
        5: c5,
        6: c6
    }

    # In Pymodbus 3.x, ModbusServerContext arg is often just 'slaves'
    # But wait, signature is (slaves=None, single=True) usually.
    # Error said unexpected keyword 'slaves'.
    # Checking Pymodbus 3 source or doc via trial...
    # It might be positional only or renamed?
    # Let's try positional.
    context = ModbusServerContext(store, single=False)

    address = ("", port)
    server = await StartAsyncTcpServer(
        context=context,
        address=address,
        # defer_start=False # removed in v3
    )
    # Server runs forever in StartAsyncTcpServer?
    # v3.0: it returns a future or runs forever?
    # v3.11: StartAsyncTcpServer is a coroutine that runs the server.
    return server

if __name__ == "__main__":
    asyncio.run(run_server())
