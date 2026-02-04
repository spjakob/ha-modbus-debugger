"""Formatting helpers for Modbus Debugger."""
import struct

class TraceLogger:
    """Helper to collect and format trace logs for the UI."""
    def __init__(self):
        self._trace = []

    def log(self, message: str):
        """Add a message to the trace, stripping common log prefixes."""
        clean_msg = message
        for prefix in ["DEBUG: ", "INFO: ", "WARNING: ", "ERROR: "]:
            if clean_msg.startswith(prefix):
                clean_msg = clean_msg[len(prefix):]
        self._trace.append(clean_msg)

    def get_trace(self) -> list[str]:
        """Return the collected trace."""
        return self._trace

class TableFormatter:
    """Helper to format register data into a table."""

    @staticmethod
    def format_read_result(registers: list[int], start_addr: int, data_type_filter: str) -> list[dict]:
        """Format a list of 16-bit registers into a table of various types."""
        rows = []
        for i, val in enumerate(registers):
            addr = start_addr + i

            # Basic 16-bit values
            row = {
                "address": addr,
                "uint16": val,
                "int16": struct.unpack(">h", struct.pack(">H", val))[0],
                "hex": f"0x{val:04X}",
                "bin": f"{val:016b}",
                "char": chr(val) if 32 <= val <= 126 else "."
            }

            # Float16 (if available)
            try:
                row["float16"] = struct.unpack(">e", struct.pack(">H", val))[0]
            except Exception:
                row["float16"] = None

            # 32-bit values (require next register)
            if i + 1 < len(registers):
                next_val = registers[i+1]
                # Big Endian (ABCD)
                be_bytes = struct.pack(">HH", val, next_val)
                row["uint32_be"] = struct.unpack(">I", be_bytes)[0]
                row["int32_be"] = struct.unpack(">i", be_bytes)[0]
                row["float32_be"] = struct.unpack(">f", be_bytes)[0]

                # Little Endian Swap (CDAB)
                le_swap_bytes = struct.pack(">HH", next_val, val)
                row["uint32_le_swap"] = struct.unpack(">I", le_swap_bytes)[0]
                row["int32_le_swap"] = struct.unpack(">i", le_swap_bytes)[0]
                row["float32_le_swap"] = struct.unpack(">f", le_swap_bytes)[0]
            else:
                row["uint32_be"] = None
                row["int32_be"] = None
                row["float32_be"] = None
                row["uint32_le_swap"] = None
                row["int32_le_swap"] = None
                row["float32_le_swap"] = None

            # Apply filter if not 'all'
            if data_type_filter == "all":
                rows.append(row)
            else:
                if data_type_filter in row and row[data_type_filter] is not None:
                    filtered_row = {
                        "address": addr,
                        data_type_filter: row[data_type_filter]
                    }
                    rows.append(filtered_row)

        return rows
