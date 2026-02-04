"""Modbus Debugger Heuristics."""


def check_fast_timeout(timeout: float) -> str | None:
    """Check if timeout is too short."""
    if timeout < 0.6:
        return (
            "⚠️ Fast Timeout detected (< 0.6s). Most Modbus Gateways require at "
            "least 600ms to process requests. This may cause missed responses."
        )
    return None


def check_non_standard_port(port: int, connection_type: str) -> str | None:
    """Check for non-standard TCP port."""
    if connection_type == "tcp" and port != 502:
        return (
            f"⚠️ Non-Standard Port ({port}) detected. Ensure this is intentional. "
            "Modbus TCP typically uses port 502."
        )
    return None


def check_silent_gateway(
    found_devices: int, error_count: int, scanned_count: int
) -> str | None:
    """Check for 'Silent Gateway' behavior (Multi-Host silence)."""
    if scanned_count > 0 and found_devices == 0 and error_count == 0:
        return (
            "⚠️ Silent Gateway detected. No devices found and NO errors received. "
            "This often happens when another client (e.g., a background service) "
            "is holding the connection open, preventing this tool from receiving data."
        )
    return None


def check_hard_timeout(trace: list, timeout: float) -> str | None:
    """Check if multiple Hard Timeouts occurred."""
    # Count timeouts that match the configured timeout duration
    # This implies we waited the full duration and got nothing (vs a quick Connection Refused)

    # We'll need to parse the trace in the Action logic to call this, or pass stats.
    # For now, let's keep it simple.
    pass
