"""Onkyo receiver."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import logging
import socket
from typing import TYPE_CHECKING

from aioonkyo import (
    BasicReceiverInfo,
    Instruction,
    Receiver,
    ReceiverInfo,
    Status,
    Zone,
    connect,
    query,
    status,
)

from homeassistant.core import HomeAssistant

from .const import DEVICE_PROBE_TIMEOUT, WRITE_INTERVAL, ZONES

if TYPE_CHECKING:
    from . import OnkyoConfigEntry

_LOGGER = logging.getLogger(__name__)


@dataclass
class Callbacks:
    """Receiver callbacks."""

    connect: list[Callable[[bool], Awaitable[None]]] = field(default_factory=list)
    disconnect: list[Callable[[], Awaitable[None]]] = field(default_factory=list)
    update: list[Callable[[Status], Awaitable[None]]] = field(default_factory=list)

    def clear(self) -> None:
        """Clear all callbacks."""
        self.connect.clear()
        self.disconnect.clear()
        self.update.clear()


class ReceiverManager:
    """Receiver manager."""

    hass: HomeAssistant
    entry: OnkyoConfigEntry
    info: ReceiverInfo
    receiver: Receiver | None = None
    connected: bool = False
    callbacks: Callbacks

    _started: asyncio.Event
    _write_lock: asyncio.Lock
    _last_write: float = 0.0

    def __init__(
        self, hass: HomeAssistant, entry: OnkyoConfigEntry, info: ReceiverInfo
    ) -> None:
        """Init receiver manager."""
        self.hass = hass
        self.entry = entry
        self.info = info
        self.callbacks = Callbacks()
        self._started = asyncio.Event()
        self._write_lock = asyncio.Lock()

    async def start(self) -> Awaitable[None] | None:
        """Start the receiver manager run.

        Returns `None`, if everything went fine.
        Returns an awaitable with exception set, if something went wrong.
        """
        manager_task = self.entry.async_create_background_task(
            self.hass, self._run(), "run_connection"
        )
        wait_for_started_task = asyncio.create_task(self._started.wait())
        done, _ = await asyncio.wait(
            (manager_task, wait_for_started_task), return_when=asyncio.FIRST_COMPLETED
        )
        if manager_task in done:
            # Something went wrong, so let's return the manager task,
            # so that it can be awaited to error out
            wait_for_started_task.cancel()
            await asyncio.wait((wait_for_started_task,))
            return manager_task

        return None

    async def _run(self) -> None:
        """Run the connection to the receiver."""
        reconnect = False
        while True:
            try:
                async with connect(self.info, retry=reconnect) as self.receiver:
                    self.connected = True
                    if not reconnect:
                        self._started.set()
                    else:
                        _LOGGER.info("Reconnected: %s", self.info)

                    await self.on_connect(reconnect=reconnect)

                    while message := await self.receiver.read():
                        await self.on_update(message)

                reconnect = True

            finally:
                self.connected = False
                _LOGGER.info("Disconnected: %s", self.info)
                await self.on_disconnect()

    async def on_connect(self, reconnect: bool) -> None:
        """Receiver (re)connected."""

        # Discover what zones are available for the receiver by querying the power.
        # If we get a response for the specific zone, it means it is available.
        for zone in ZONES:
            await self.write(query.Power(zone))

        for callback in self.callbacks.connect:
            await callback(reconnect)

    async def on_disconnect(self) -> None:
        """Receiver disconnected."""
        for callback in self.callbacks.disconnect:
            await callback()

    async def on_update(self, message: Status) -> None:
        """New message from the receiver."""
        for callback in self.callbacks.update:
            await callback(message)

    async def write(self, message: Instruction) -> None:
        """Write message to the receiver.

        Legacy receivers silently drop commands that arrive too close together,
        so the writes are spaced out.
        """
        assert self.receiver is not None
        async with self._write_lock:
            loop = asyncio.get_running_loop()
            if (delay := self._last_write + WRITE_INTERVAL - loop.time()) > 0:
                await asyncio.sleep(delay)
            await self.receiver.write(message)
            self._last_write = loop.time()

    def start_unloading(self) -> None:
        """Start unloading."""
        self.callbacks.clear()


async def async_probe(host: str, port: int) -> None:
    """Check that the receiver answers eISCP queries over TCP.

    Legacy receivers do not answer the UDP discovery (interview), so instead we
    connect directly and wait for the reply to a power query.
    """
    async with (
        asyncio.timeout(DEVICE_PROBE_TIMEOUT),
        connect(BasicReceiverInfo(host=host, port=port)) as receiver,
    ):
        await receiver.write(query.Power(Zone.MAIN))
        while message := await receiver.read():
            if isinstance(message, (status.Power, status.NotAvailable)):
                return

    raise ConnectionError(f"Receiver at {host}:{port} closed the connection")


async def async_get_identifier(hass: HomeAssistant, host: str) -> str:
    """Get a stable identifier for the receiver.

    Legacy receivers do not report their MAC address over eISCP, so we try to
    find it in the ARP table (populated by the probe connection). If it is not
    there (e.g. Home Assistant runs in a container without host networking),
    we fall back to the host.
    """
    try:
        infos = await hass.loop.getaddrinfo(host, None, family=socket.AF_INET)
    except OSError:
        return host
    ip = infos[0][4][0]

    mac = await hass.async_add_executor_job(_get_mac_from_arp_table, ip)
    if mac is None:
        _LOGGER.debug("MAC address of %s not found, using host as identifier", host)
        return host

    return mac.replace(":", "").upper()


def _get_mac_from_arp_table(ip: str) -> str | None:
    """Look up the MAC address of an IP address in the ARP table."""
    try:
        with open("/proc/net/arp", encoding="ascii") as arp_table:
            next(arp_table)  # Header
            for line in arp_table:
                fields = line.split()
                if (
                    len(fields) >= 4
                    and fields[0] == ip
                    and fields[3] != "00:00:00:00:00:00"
                ):
                    return fields[3]
    except OSError:
        pass
    return None
