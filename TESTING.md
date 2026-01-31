# Testing Guide

This project includes a robust testing framework to ensure the Modbus Debugger works correctly across different scenarios, specifically focusing on the custom `ModbusScanner` implementation.

## Overview

The test suite is divided into three main categories:

1.  **Unit Tests (`tests/test_scanner.py`)**: Tests the low-level logic of the `ModbusScanner` class (packet construction, CRC calculation, response parsing) in isolation, without any network IO.
2.  **Service Tests (`tests/test_services.py`)**: Tests the Home Assistant Service integration, ensuring that service calls (`scan_devices`, `read_register`) are correctly routed and arguments are parsed. These tests mock the `ModbusScanner` and `ModbusHub` to verify the "wiring" logic.
3.  **Integration Tests (`tests/test_scanner_integration.py`)**: Tests the actual networking and protocol handling of the `ModbusScanner` against a **Mock Modbus Gateway**. This is the most critical test for verifying scanner behavior under various network conditions.

## Mock Modbus Gateway

The integration tests use a custom **Mock Modbus Gateway** (`tests/mock_gateway.py`), built on top of `pymodbus`'s `StartAsyncTcpServer`. This gateway simulates a Modbus TCP server (or Gateway) that hosts multiple Unit IDs (slaves), each with a specific behavior designed to stress-test the scanner.

### Simulated Behaviors (Unit IDs)

The Mock Gateway maps specific Unit IDs to distinct behaviors:

| Unit ID | Behavior | Scenario Tested |
| :--- | :--- | :--- |
| **1** | **Healthy** | Returns valid register data instantly. Represents a normal, working device. |
| **2** | **Register Error** | Returns an empty response or simulates a Modbus Exception. Represents a device that is present but rejects the specific register read (e.g., Illegal Address). The scanner should report this device as "Found" (with error). |
| **3** | **Timeout (Ghost)** | Sleeping for 2.0s before responding. Represents a missing device or a device that is offline. The scanner (with a <2s timeout) should report this as "No Response". |
| **4** | **Gateway Error** | Similar to ID 2, simulates a Gateway-generated error or downstream failure. |
| **5** | **Slow Device** | Sleeps for 0.2s then returns valid data. Represents a high-latency device. The scanner should find this device if the timeout is >0.2s. |
| **6** | **Flaky** | Times out on the first request, responds successfully on the second. Tests the **Retry** logic of the scanner. |

## Running Tests

To run the full test suite:

```bash
python3 -m pytest
```

To run only the integration tests (and see live logs):

```bash
python3 -m pytest tests/test_scanner_integration.py -o log_cli=true
```

## Extending Tests

### Adding New Scenarios
To add a new test scenario (e.g., a device that returns garbage data):
1.  Open `tests/mock_gateway.py`.
2.  Create a new `ModbusSlaveContext` subclass (e.g., `GarbageContext`).
3.  Override `getValues` to implement the behavior.
4.  Add the new context to the `store` dictionary in `run_server` with a new Unit ID.
5.  Update `tests/test_scanner_integration.py` to scan the new ID and assert the expected result.

### VS Code
This project is configured to work with standard Python test runners. Ensure your environment uses the `requirements_test.txt` dependencies.
