import asyncio
import pytest
from custom_components.modbus_debugger.actions.scan import _run_scan_sync
from custom_components.modbus_debugger.const import CONNECTION_TYPE_TCP


@pytest.mark.asyncio
async def test_late_response_recovery_mocked():
    config = {
        "connection_type": CONNECTION_TYPE_TCP,
        "host": "127.0.0.1",
        "port": 502,
        "name": "Test",
    }
    from unittest.mock import patch

    with patch("custom_components.modbus_debugger.actions.scan.get_client") as MC:
        client = MC.return_value
        from custom_components.modbus_debugger.modbus_core.client import LateResponse

        client._late_responses = [LateResponse(101, 3, bytes.fromhex("021111"))]
        client.execute.return_value = bytes.fromhex("022222")

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, _run_scan_sync, config, 107, 107, 0, 3, 1.0, 0, "detailed", False
        )

        # Should find both 107 (from execute) and 101 (from late_responses)
        units = [d["unit_id"] for d in result["found_devices"]]
        assert 107 in units
        assert 101 in units
        assert any(
            "Late Recovery" in str(d.get("value"))
            for d in result["found_devices"]
            if d["unit_id"] == 101
        )
