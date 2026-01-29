# Home Assistant Modbus Debugger

A powerful and simple tool to debug Modbus devices (RTU & TCP) directly within Home Assistant.

This integration allows you to:
1.  **Debug Connections**: Read raw register data from any Modbus device without creating permanent sensors first.
2.  **View Data Formats**: Instantly see register values decoded as Int16, Int32 (Big Endian & Word Swapped), Float16, Float32, Hex, and String.
3.  **Scan for Devices**: Scan a range of Unit IDs to discover devices on your bus.
4.  **Create Sensors**: Easily save working queries as permanent Home Assistant sensors.
5.  **Monitor Health**: Track success/failure statistics for each device.

---

## Installation

### Option 1: HACS (Recommended)
1.  Open HACS in Home Assistant.
2.  Go to **Integrations** > **Custom repositories**.
3.  Add the URL of this repository.
4.  Select **Modbus Debugger** and install.
5.  Restart Home Assistant.

### Option 2: Manual
1.  Copy the `custom_components/ha_modbus_debugger` folder to your Home Assistant `config/custom_components/` directory.
2.  Restart Home Assistant.

---

## Configuration

1.  Go to **Settings** > **Devices & Services**.
2.  Click **Add Integration**.
3.  Search for **Modbus Debugger**.
4.  Choose your connection type:
    *   **TCP**: Enter Host IP and Port (default 502).
    *   **Serial (RTU)**: Enter Port (e.g., `/dev/ttyUSB0`), Baudrate, Parity, etc.

You can add multiple hubs (e.g., one TCP gateway and one local USB adapter).

---

## Usage

### 1. Debugging (Read Register)
To read a register and check its value:
1.  Go to **Developer Tools** > **Actions** (or Services).
2.  Select `modbus_debugger.read_register`.
3.  Fill in the fields:
    *   **Hub ID**: Select your configured hub.
    *   **Unit ID**: The Modbus Slave ID (1-247).
    *   **Register Address**: The address to read (0-65535).
    *   **Count**: Number of registers (default 1).
    *   **Register Type**: Holding or Input.
4.  Click **Perform Action**.
5.  The result will show the raw hex values and decoded values in various formats (Int16, Float32, String, etc.).

### 2. Scanning for Devices
To find what devices are on your bus:
1.  Go to **Developer Tools** > **Actions**.
2.  Select `modbus_debugger.scan_devices`.
3.  Enter the **Start Unit ID** and **End Unit ID** (e.g., 1 to 10).
4.  Click **Perform Action**.
5.  The output will list all Unit IDs that responded to a read request.

### 3. Creating Sensors
Once you have identified the correct register settings:
1.  Go to **Settings** > **Devices & Services** > **Modbus Debugger**.
2.  Click **Configure** on your Hub.
3.  Select **Add Sensor**.
4.  Enter the Name, Unit ID, Register, and Data Type.
5.  The sensor will be created (e.g., `sensor.my_voltage`) and will update automatically.

### 4. Monitoring Health
For every device (Unit ID) you add sensors for, the integration automatically creates statistics sensors:
*   `sensor.device_X_success_count`
*   `sensor.device_X_fail_count`

Use these to monitor the stability of your Modbus network.
