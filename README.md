# Home Assistant Modbus Debugger: Diagnostic Toolbox

A robust "Diagnostic Toolbox" to troubleshoot, benchmark, and discover Modbus devices (RTU & TCP) directly within Home Assistant.

### Key Features
*   **Independent Driver**: Builds on a custom, synchronous Modbus implementation (using `socket` and `pyserial`). It operates completely **independently of `pymodbus`**, ensuring no conflicts and allowing for specialized low-level control.
*   **Device Discovery**: Scan your bus to find responding Slave IDs.
*   **Traffic Analysis**: View raw TX/RX packets with decoded MBAP headers and function codes.
*   **Stress Testing**: Benchmark connection stability, latency, and throughput to identify flaky wiring or hardware.
*   **Intelligent Heuristics**: Automatically detects and warns about:
    *   Zero-latency responses (Gateway Caching)
    *   Silent Gateways (Connection blocking)
    *   Connection Refusals vs Timeouts

---

## Actions (Services)

### 1. Read Register (`modbus_debugger.read_register`)
Read raw data from a device and see it decoded instantly (Int16, Float32, Hex, etc.).
- **Slave ID**: Address of the target device (1-247).
- **Register**: Starting address.
- **Trace**: See the exact query sent and response received.

### 2. Scan Devices (`modbus_debugger.scan_devices`)
Iterate through a range of Slave IDs to find active devices.
- **Range**: Start and End Slave ID.
- **Scan Mode**:
    - **Standard**: Sequential, safe scan (wait for timeout on each).
    - **Smart**: Rapidly scans the entire range to detect active devices much faster than the standard method.

### 3. Stress Test (`modbus_debugger.stress_test`)
Hammer a device with requests to verify stability.
- **Throughput**: Measure actual bus speed in bits per second.
- **Error Analysis**: Distinguishes between network failures (IP/Port) and device failures (Wiring/Baudrate).

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

## Configuration

1.  Go to **Settings** > **Devices & Services**.
2.  Click **Add Integration**.
3.  Search for **Modbus Debugger**.
4.  Choose your connection type:
    *   **TCP**: Enter Host IP and Port (default 502).
    *   **Serial (RTU)**: Enter Port (e.g., `/dev/ttyUSB0`), Baudrate, Parity, etc.

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
