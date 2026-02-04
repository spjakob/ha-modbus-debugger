# Home Assistant Modbus Debugger: Diagnostic Toolbox

A robust "Diagnostic Toolbox" to troubleshoot and benchmark Modbus devices (RTU & TCP) directly within Home Assistant.

Unlike standard integrations that focus on polling, this tool is designed for **low-level bus analysis** and **device discovery**. It uses a custom synchronous driver to ensure predictable sequential communication, making it ideal for troubleshooting complex RS485 networks.

## Why this integration?

Modbus communication, especially over serial (RS485), is prone to "Head-of-Line Blocking" and "Pipeline Desync." This integration solves these issues with:
- **Sequential Execution**: All requests are sent strictly one-by-one to avoid gateway congestion.
- **Smart Drain**: Before every request, the input buffer is cleared to discard "Ghost Data" (leftovers from previous timeouts).
- **Late Response Recovery**: If a device responds after a timeout, the scanner captures it as a "Late Recovery" result instead of misassigning the data to the next device.

---

## Features

1.  **Read & Decode Registers**: Read raw register data and see it decoded as Int16, Int32, Float32, Hex, and Char.
2.  **Sequential Scanning**: Discovery of Unit IDs on your bus with built-in recovery for late-responding devices.
3.  **Stress Testing**: Benchmark device latency and success rates under heavy load to identify flaky hardware or wiring.
4.  **Heuristic Warnings**: Get tips on non-standard ports, fast timeouts, or silent gateways.

---

## Installation

### via HACS (Recommended)
1. Ensure [HACS](https://hacs.xyz/) is installed.
2. Go to HACS -> Integrations -> 3 dots (top right) -> Custom repositories.
3. Paste `https://github.com/spjakob/ha-modbus-debugger` and select Category `Integration`.
4. Click **Add**, then find **Modbus Debugger** and click **Download**.
5. Restart Home Assistant.

### Manual
1. Copy the `custom_components/modbus_debugger` folder to your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

---

## Technical Status

> [!IMPORTANT]
> **Independent Implementation**: This integration uses a native, synchronous Modbus driver built directly on `socket` and `pyserial`. It is **NOT** dependent on `pymodbus`, which allows for the specialized error recovery and timing analysis features.

> [!WARNING]
> **Experimental Features**: While Modbus TCP is stable, **Serial (RTU)** and **RTU-over-TCP** support are considered experimental. They require more community feedback and are not yet 100% tested across all hardware variants.

---

## Configuration

1.  Go to **Settings** > **Devices & Services**.
2.  Click **Add Integration**.
3.  Search for **Modbus Debugger**.
4.  Choose your connection type:
    *   **TCP**: Enter Host IP and Port (default 502).
    *   **Serial (RTU)**: Enter Port (e.g., `/dev/ttyUSB0`), Baudrate, Parity, etc.

---

## Actions (Services)

### 1. Read Register (`modbus_debugger.read_register`)
Read a range of registers and view a formatted table of interpretations.
- **Hub ID**: The configured connection profile.
- **Unit ID**: Slave ID (1-247).
- **Register Address**: Start address.
- **Count**: Number of registers (auto-chunks into Modbus-compliant requests).

### 2. Scan Devices (`modbus_debugger.scan_devices`)
Discover devices on the bus by checking for responses across a range of Unit IDs.
- **Range**: Start and End Unit ID.
- **Late Recovery**: Automatically logs if a device responded late during the scan.

### 3. Stress Test (`modbus_debugger.stress_test_device`)
Measure the reliability of a device by sending multiple requests in rapid succession.
- **Iterations**: Number of requests to send (default 50).
- **Statistics**: Returns success rate, min/max/avg latency.

---

## Development

1.  **Install test requirements:**
    ```bash
    pip install -r requirements_test.txt
    ```

2.  **Run tests:**
    ```bash
    python -m pytest tests/
    ```

For detailed information on the architecture, see [TESTING.md](TESTING.md).
