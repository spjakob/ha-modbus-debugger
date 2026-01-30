"""Integration tests for library compatibility."""
import sys
import types
from unittest.mock import MagicMock
import pytest

from custom_components.ha_modbus_debugger.modbus import ModbusHub
from custom_components.ha_modbus_debugger.const import (
    CONF_CONNECTION_TYPE,
    CONF_HOST,
    CONF_PORT,
    CONF_TIMEOUT,
    CONNECTION_TYPE_TCP,
    CONF_RTU_OVER_TCP
)

@pytest.mark.asyncio
async def test_real_client_instantiation():
    """
    Test that the ModbusHub can instantiate a REAL pymodbus client
    without crashing due to version incompatibilities (like the FramerType issue).
    """
    config = {
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP,
        CONF_HOST: "127.0.0.1",
        CONF_PORT: 5020,
        CONF_TIMEOUT: 1,
        CONF_RTU_OVER_TCP: False
    }

    hub = ModbusHub(config)

    # This calls AsyncModbusTcpClient(...)
    # If the framer argument is wrong, it will raise TypeError here or inside connect()
    try:
        # We expect this to fail connection (no server), but NOT raise TypeError
        success = await hub.connect()
        assert success is False
        assert hub.last_error is not None
        # Ensure we didn't get "socket closed" immediately due to bad init,
        # though "Connection refused" is the most likely error.
    except TypeError as e:
        pytest.fail(f"ModbusHub failed to instantiate client due to TypeError: {e}")
    except Exception as e:
        # Unexpected crashes
        pytest.fail(f"ModbusHub crashed with unexpected error: {type(e).__name__}: {e}")

@pytest.mark.asyncio
async def test_comm_params_compatibility():
    """
    Test that the client object created has 'comm_params' and we can access/modify
    timeout on it, matching the logic used in 'scan_devices'.
    """
    config = {
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP,
        CONF_HOST: "127.0.0.1",
        CONF_PORT: 5020,
        CONF_TIMEOUT: 1,
        CONF_RTU_OVER_TCP: False
    }

    hub = ModbusHub(config)

    # Use a dummy client to avoid needing a real connection for this test
    # BUT we want to use the REAL AsyncModbusTcpClient to verify comm_params structure.
    # The problem is hub.connect() destroys the client on failure.
    # So we manually create it using the same logic as hub.connect()

    # Initialize client manually to inspect it without connection failure clearing it
    from pymodbus.client import AsyncModbusTcpClient
    from pymodbus.framer import FramerType

    hub._client = AsyncModbusTcpClient(
        host=config[CONF_HOST],
        port=config[CONF_PORT],
        framer=FramerType.SOCKET,
        timeout=config[CONF_TIMEOUT]
    )

    assert hub._client is not None

    # Check for comm_params existence (pymodbus v3 standard)
    assert hasattr(hub._client, "comm_params"), "comm_params missing on client (pymodbus v3+ required)"
    
    comm_params = hub._client.comm_params

    # Verify we can find a timeout attribute (either 'timeout' or 'timeout_connect')
    has_timeout = hasattr(comm_params, "timeout")
    has_timeout_connect = hasattr(comm_params, "timeout_connect")

    assert has_timeout or has_timeout_connect, \
        f"comm_params found but has neither 'timeout' nor 'timeout_connect'. Dir: {dir(comm_params)}"

    # Verify we can write to it (simulate what scan_devices does)
    try:
        if has_timeout:
            comm_params.timeout = 0.5
            assert comm_params.timeout == 0.5
        elif has_timeout_connect:
            comm_params.timeout_connect = 0.5
            assert comm_params.timeout_connect == 0.5
    except Exception as e:
        pytest.fail(f"Failed to modify timeout attribute on comm_params: {e}")

