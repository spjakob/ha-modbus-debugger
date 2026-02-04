# Modbus Diagnostic Toolbox

A specialized Home Assistant integration designed for robust Modbus debugging and bus analysis. Unlike standard Modbus integrations that focus on persistent sensor polling, this toolbox provides high-level diagnostic actions with built-in self-healing capabilities for complex serial-over-TCP environments.

## Features

- **Actions-Only Provider**: Lightweight integration that only provides diagnostic services, avoiding background polling overhead.
- **Custom Synchronous Core**: Uses a specialized synchronous driver to prevent "Head-of-Line Blocking" common in async RS485 gateways.
- **Smart Drain**: Automatically clears "Ghost Data" from previous timeouts before sending new requests.
- **Late Response Recovery**: Captures and identifies delayed responses from slow devices, preventing pipeline desynchronization.
- **Address Book Config Flow**: Save connection profiles for multiple gateways and reference them by hub ID in diagnostic actions.
- **Advanced Heuristics**: Automatic warnings for non-standard ports, aggressive timeouts, and silent buses.

## Services

### `scan_devices`
Scans a range of Unit IDs on the bus. Captures late responses and reports found devices along with latency and status.

### `read_register`
Reads registers from a specific device and formats the data into a comprehensive table showing multiple data types (Int16, UInt16, Float32, etc.) simultaneously.

### `stress_test_device`
Performs multiple rapid-fire requests to a device to analyze success rates and average latency under load.

## Core Rationale: Sequential vs. Async
Standard Modbus TCP clients often fail on RS485 gateways when multiple requests are queued. This integration solves this by enforcing strict sequential execution and implementing a "Read-Until-Match" strategy that can recover responses even if they arrive out-of-sync with the current request.

## Development
See `DEVELOPMENT.TXT` for a deep dive into the architecture and technical rationale.
