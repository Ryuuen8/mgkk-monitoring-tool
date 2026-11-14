"""Async UDP/TCP syslog receiver.

Critical messages are matched to inventory devices by source address, stored in
PostgreSQL, and published on the Redis event bus for the live WebSocket feed.
"""

import asyncio
import ipaddress
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.db.session import SessionLocal
from app.models import Device, SyslogEvent
from app.services import events
from app.syslog.parsers import is_critical, parse_syslog

logger = logging.getLogger(__name__)

MAX_MESSAGE_BYTES = 65_535
MAX_TCP_BUFFER = MAX_MESSAGE_BYTES * 2
Processor = Callable[[str, str], Awaitable[bool]]


def _canonical_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return value


async def _match_device(session: AsyncSession, source_ip: str) -> Device | None:
    try:
        address = ipaddress.ip_address(source_ip)
    except ValueError:
        return None
    return await session.scalar(
        select(Device)
        .where(Device.mgmt_ip == address)
        .options(selectinload(Device.site))
    )


async def process_message(
    raw: str,
    source_ip: str,
    *,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
    min_severity: int | None = None,
    now: datetime | None = None,
) -> bool:
    """Parse, persist, and publish one syslog message when it is critical."""
    parsed = parse_syslog(raw, now)
    threshold = (
        min_severity
        if min_severity is not None
        else int(os.getenv("SYSLOG_MIN_SEVERITY", "5"))
    )
    if not is_critical(parsed, threshold):
        return False

    source = _canonical_ip(source_ip)
    async with session_factory() as session:
        device = await _match_device(session, source)
        row = SyslogEvent(
            device_id=device.id if device is not None else None,
            source_ip=source,
            facility=parsed.facility,
            severity=parsed.severity,
            hostname=(parsed.hostname or (device.name if device else None)),
            app_name=parsed.app_name,
            event_type=parsed.event_type,
            message=parsed.message,
            raw=parsed.raw,
            occurred_at=parsed.occurred_at,
        )
        session.add(row)
        await session.commit()
        payload: dict[str, Any] = {
            "syslog_id": str(row.public_id),
            "device": device.name if device is not None else None,
            "device_id": str(device.public_id) if device is not None else None,
            "site": device.site.code if device is not None and device.site else None,
            "source_ip": source,
            "severity": parsed.severity,
            "facility": parsed.facility,
            "event_type": parsed.event_type,
            "hostname": parsed.hostname,
            "app_name": parsed.app_name,
            "message": parsed.message,
            "occurred_at": parsed.occurred_at.isoformat(),
        }
    await events.publish_event("syslog_event", payload)
    return True


class _UDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: "SyslogServer") -> None:
        self.server = server
        self.transport: asyncio.DatagramTransport | None = None
        self.tasks: set[asyncio.Task[None]] = set()

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if len(data) > MAX_MESSAGE_BYTES:
            logger.warning("Dropping oversized syslog datagram from %s", addr[0])
            return
        task = asyncio.create_task(self.server.receive(data, addr[0]))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def error_received(self, exc: Exception) -> None:
        logger.info("Syslog UDP error: %s", type(exc).__name__)


def _next_frame(buffer: bytes) -> tuple[bytes | None, bytes]:
    """Extract one newline-delimited or octet-counted (RFC 6587) frame."""
    if not buffer:
        return None, buffer
    if buffer[:1].isdigit():
        space = buffer.find(b" ")
        if space != -1:
            try:
                length = int(buffer[:space])
            except ValueError:
                length = -1
            if length >= 0:
                end = space + 1 + length
                if len(buffer) < end:
                    return None, buffer
                return buffer[space + 1 : end], buffer[end:]
    newline = buffer.find(b"\n")
    if newline == -1:
        return None, buffer
    return buffer[:newline].rstrip(b"\r"), buffer[newline + 1 :]


class SyslogServer:
    def __init__(
        self,
        host: str,
        port: int,
        *,
        min_severity: int | None = None,
        processor: Processor | None = None,
        max_concurrent: int = 50,
    ) -> None:
        self.host = host
        self.port = port
        self.min_severity = min_severity
        self.processor = processor
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._udp: asyncio.DatagramTransport | None = None
        self._tcp: asyncio.AbstractServer | None = None

    async def _process(self, raw: str, source_ip: str) -> bool:
        async with self._semaphore:
            if self.processor is not None:
                return await self.processor(raw, source_ip)
            return await process_message(raw, source_ip, min_severity=self.min_severity)

    async def receive(self, data: bytes, source_ip: str) -> None:
        raw = data.decode("utf-8", errors="replace").strip()
        if not raw:
            return
        try:
            await self._process(raw, source_ip)
        except Exception as exc:  # noqa: BLE001 - one bad message must not stop the listener
            logger.warning(
                "Failed to process syslog from %s: %s", source_ip, type(exc).__name__
            )

    async def _handle_tcp(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        source_ip = str(peer[0]) if peer else ""
        buffer = b""
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                buffer += chunk
                if len(buffer) > MAX_TCP_BUFFER:
                    logger.warning("Syslog TCP buffer overflow from %s", source_ip)
                    break
                while True:
                    frame, buffer = _next_frame(buffer)
                    if frame is None:
                        break
                    await self.receive(frame, source_ip)
        except (ConnectionError, OSError) as exc:
            logger.info("Syslog TCP connection error: %s", type(exc).__name__)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._udp, _ = await loop.create_datagram_endpoint(
            lambda: _UDPProtocol(self), local_addr=(self.host, self.port)
        )
        self._tcp = await asyncio.start_server(self._handle_tcp, self.host, self.port)
        logger.info(
            "Syslog receiver listening on %s:%d (UDP+TCP)", self.host, self.port
        )

    async def stop(self) -> None:
        if self._udp is not None:
            self._udp.close()
            self._udp = None
        if self._tcp is not None:
            self._tcp.close()
            await self._tcp.wait_closed()
            self._tcp = None

    async def serve_forever(self) -> None:
        await self.start()
        try:
            await asyncio.Event().wait()
        finally:
            await self.stop()


async def serve() -> None:
    load_dotenv()
    host = os.getenv("SYSLOG_HOST", "0.0.0.0")
    port = int(os.getenv("SYSLOG_PORT", "5514"))
    min_severity = int(os.getenv("SYSLOG_MIN_SEVERITY", "5"))
    server = SyslogServer(host, port, min_severity=min_severity)
    await server.serve_forever()


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
