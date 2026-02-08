"""Formatting helpers for Modbus Debugger (TraceLogger, TableFormatter)."""


import struct


class TraceLogger:
    """Helper to collect execution trace logs."""

    def __init__(self):
        self._trace = []

    def log(self, message: str):
        """Add a message to the trace."""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._trace.append(f"[{timestamp}] {message}")

    def get_trace(self) -> list[str]:
        """Return the collected trace."""
        return self._trace


class TableFormatter:
    """Helper to format Modbus register data into a table."""

    @staticmethod
    def format_read_result(
        registers: list[int], start_address: int, data_type_filter: str = "all"
    ) -> list[dict]:
        """Format a list of 16-bit registers into a detailed table."""
        table = []
        
        # Helper to get 32-bit values
        def get_32bit(idx, endianness='big'):
            if idx + 1 >= len(registers):
                return None
            hi = registers[idx]
            lo = registers[idx+1]
            if endianness == 'big':
                return (hi << 16) | lo
            elif endianness == 'little':
                 # Standard Modbus "Little Endian" usually means [CD] [AB] for 0xABCD? 
                 # Or [AB] [CD]? 
                 # Let's stick to the requested names and standard conventions.
                 return (lo << 16) | hi
            return 0

        # Formatters
        def to_hex(val): return f"0x{val:04X}"
        def to_int16(val): return str(struct.unpack('>h', struct.pack('>H', val))[0])
        def to_uint16(val): return val # Return as integer for consistency
        def to_float16(val):
            try: return f"{struct.unpack('>e', struct.pack('>H', val))[0]:.4f}"
            except: return "N/A"
        def to_char(val):
            b_hi = (val >> 8) & 0xFF
            b_lo = val & 0xFF
            c_hi = chr(b_hi) if 32 <= b_hi <= 126 else '.'
            c_lo = chr(b_lo) if 32 <= b_lo <= 126 else '.'
            return f"{c_hi}{c_lo}"
        def to_float32(val_32):
            if val_32 is None: return "-"
            return f"{struct.unpack('>f', struct.pack('>I', val_32))[0]:.4f}"
        def to_int32(val_32):
            if val_32 is None: return "-"
            return str(struct.unpack('>i', struct.pack('>I', val_32))[0])
        def to_uint32(val_32):
            if val_32 is None: return "-"
            return str(val_32)

        for idx, val in enumerate(registers):
            reg_addr = start_address + idx
            
            row = {"address": reg_addr}
            
            # 16-bit values and base types
            if data_type_filter in ['all', 'hex']: row["hex"] = to_hex(val)
            if data_type_filter in ['all', 'int16']: row["int16"] = to_int16(val)
            if data_type_filter in ['all', 'uint16']: row["uint16"] = to_uint16(val)
            if data_type_filter in ['all', 'bin']: row["binary"] = f"{val:016b}"
            if data_type_filter in ['all', 'char']: row["char"] = to_char(val)
            if data_type_filter in ['all', 'float16']: row["float16"] = to_float16(val)

            # 32-bit values (Lookahead)
            if idx + 1 < len(registers):
                val32_be = get_32bit(idx, 'big')
                val32_le = get_32bit(idx, 'little')

                if data_type_filter in ['all', 'int32_be']: row["int32_be"] = to_int32(val32_be)
                if data_type_filter in ['all', 'uint32_be']: row["uint32_be"] = to_uint32(val32_be)
                if data_type_filter in ['all', 'float32_be']: row["float32_be"] = to_float32(val32_be)
                
                if data_type_filter in ['all', 'int32_le_swap']: row["int32_le_swap"] = to_int32(val32_le)
                if data_type_filter in ['all', 'float32_le_swap']: row["float32_le_swap"] = to_float32(val32_le)

                # Backwards compatibility / Explicit requests
                if data_type_filter == 'int32': row["int32"] = to_int32(val32_be)
                if data_type_filter == 'uint32': row["uint32"] = to_uint32(val32_be)
                if data_type_filter == 'float32': row["float32"] = to_float32(val32_be)

            table.append(row)
            
        return table
