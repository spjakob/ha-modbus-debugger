"""Formatting helpers for Modbus Debugger."""
import struct

class TraceLogger:
    """Helper to collect execution trace logs."""
    def __init__(self):
        self._trace = []

    def log(self, message: str):
        """Add a message to the trace."""
        self._trace.append(message)

    def get_trace(self) -> list[str]:
        """Return the collected trace."""
        return self._trace

class TableFormatter:
    """Helper to format Modbus register data into a table."""

    @staticmethod
    def format_read_result(registers: list[int], start_address: int, data_type_filter: str = "all") -> list[dict]:
        """Format a list of 16-bit registers into a detailed table."""
        table = []
        for i, val in enumerate(registers):
            addr = start_address + i
            row = {
                "address": addr,
                "uint16": val,
                "int16": struct.unpack(">h", struct.pack(">H", val))[0],
                "hex": f"0x{val:04X}"
            }
            chars = struct.pack(">H", val)
            row["char"] = "".join(chr(b) if 32 <= b <= 126 else "." for b in chars)
            if i + 1 < len(registers):
                next_val = registers[i+1]
                combined = (val << 16) | next_val
                row["uint32"] = combined
                row["int32"] = struct.unpack(">i", struct.pack(">I", combined))[0]
                row["float32"] = round(struct.unpack(">f", struct.pack(">I", combined))[0], 4)
            if data_type_filter != "all":
                filtered_row = {"address": addr}
                if data_type_filter in row:
                    filtered_row[data_type_filter] = row[data_type_filter]
                row = filtered_row
            table.append(row)
        return table
