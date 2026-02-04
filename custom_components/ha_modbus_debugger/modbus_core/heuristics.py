def check_fast_timeout(timeout: float) -> str | None:
    if timeout < 0.6:
        return "Warning: Fast timeout detected. Many gateways require at least 600ms."
    return None

def check_non_standard_port(port: int, connection_type: str) -> str | None:
    if connection_type == "tcp" and port != 502:
        return f"Using non-standard port {port}. Ensure your gateway is configured correctly."
    return None

def check_silent_gateway(found_count: int, error_count: int, total_scanned: int) -> str | None:
    if found_count == 0 and error_count == 0 and total_scanned > 0:
        return "No devices found and no timeouts. Your gateway may be silent or using an incompatible protocol."
    return None
