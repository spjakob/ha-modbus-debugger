"""Modbus Hub implementation."""

import logging
import asyncio
from typing import Any, Union

from pymodbus.client import (
    AsyncModbusTcpClient,
    AsyncModbusSerialClient,
)
from pymodbus.exceptions import ModbusException
from pymodbus.pdu import ExceptionResponse, ModbusPDU

from .const import (
    CONF_CONNECTION_TYPE,
    CONF_HOST,
    CONF_PORT,
    CONF_BAUDRATE,
    CONF_PARITY,
    CONF_STOPBITS,
    CONF_BYTESIZE,
    CONF_TIMEOUT,
    CONNECTION_TYPE_TCP,
    CONNECTION_TYPE_SERIAL,
)

_LOGGER = logging.getLogger(__name__)


class ModbusHub:
    """Thread safe wrapper class for pymodbus."""

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize the Modbus hub."""
        self._config = config
        self._client = None
        self._lock = asyncio.Lock()
        self._connection_type = config[CONF_CONNECTION_TYPE]
        self._stats = {}

    def report_stat(self, unit_id: int, success: bool):
        """Update statistics for a unit."""
        if unit_id not in self._stats:
            self._stats[unit_id] = {"success": 0, "fail": 0}

        if success:
            self._stats[unit_id]["success"] += 1
        else:
            self._stats[unit_id]["fail"] += 1

    def get_stats(self, unit_id: int):
        """Get statistics for a unit."""
        return self._stats.get(unit_id, {"success": 0, "fail": 0})

    async def connect(self) -> bool:
        """Connect to the Modbus device."""
        if self._client:
            if self._client.connected:
                return True

        if self._connection_type == CONNECTION_TYPE_TCP:
            self._client = AsyncModbusTcpClient(
                self._config[CONF_HOST],
                port=self._config[CONF_PORT],
                timeout=self._config.get(CONF_TIMEOUT, 3),
            )
        elif self._connection_type == CONNECTION_TYPE_SERIAL:
            self._client = AsyncModbusSerialClient(
                self._config[CONF_PORT],
                baudrate=self._config[CONF_BAUDRATE],
                stopbits=self._config[CONF_STOPBITS],
                bytesize=self._config[CONF_BYTESIZE],
                parity=self._config[CONF_PARITY],
                timeout=self._config.get(CONF_TIMEOUT, 3),
            )

        try:
            await self._client.connect()
        except ModbusException as exc:
            _LOGGER.error("Error connecting to modbus: %s", exc)
            return False

        return self._client.connected

    async def close(self) -> None:
        """Disconnect client."""
        if self._client:
            self._client.close()

    async def read_holding_registers(
        self, slave: int, address: int, count: int
    ) -> Union[ModbusPDU, ExceptionResponse, None]:
        """Read holding registers."""
        if not self._client or not self._client.connected:
            await self.connect()

        async with self._lock:
            try:
                result = await self._client.read_holding_registers(
                    address, count=count, slave=slave
                )
            except ModbusException as exc:
                _LOGGER.error("Pymodbus: Error reading holding registers: %s", exc)
                return None

            return result

    async def read_input_registers(
        self, slave: int, address: int, count: int
    ) -> Union[ModbusPDU, ExceptionResponse, None]:
        """Read input registers."""
        if not self._client or not self._client.connected:
            await self.connect()

        async with self._lock:
            try:
                result = await self._client.read_input_registers(
                    address, count=count, slave=slave
                )
            except ModbusException as exc:
                _LOGGER.error("Pymodbus: Error reading input registers: %s", exc)
                return None

            return result
