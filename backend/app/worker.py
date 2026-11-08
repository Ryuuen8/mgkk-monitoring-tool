"""DB-driven ICMP poller.

Reads active, ping-enabled devices from PostgreSQL, pings each one on its own
`poll_interval_seconds`, caches `last_seen_at` on success, and publishes
Prometheus gauges for the API/Grafana to read.

Runs as its own process (`python -m app.worker`), so the API stays responsive
and can be scaled independently of polling.
"""

import asyncio
import logging
import math
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from dotenv import load_dotenv
from prometheus_client import Gauge, start_http_server
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.db.session import SessionLocal
from app.models import CredentialType, Device, DeviceCheckType
from app.services.credentials import decrypt_secret

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# Labels stay low-cardinality: name and site code, never tags or IPs.
DEVICE_UP = Gauge(
    "device_up",
    "1 when the last configured device check succeeded, else 0",
    ("device", "site"),
)
PING_LATENCY = Gauge(
    "ping_latency_seconds",
    "Round-trip time in seconds of the last device check",
    ("device", "site"),
)
PING_PACKET_LOSS = Gauge(
    "ping_packet_loss_ratio",
    "ICMP packet loss ratio (0-1) of the last poll",
    ("device", "site"),
)

# NaN marks "no latency sample" so range queries can leave a gap instead of
# carrying a stale value across an outage.
NO_SAMPLE = float("nan")

DEFAULT_TICK_SECONDS = 5.0


@dataclass(frozen=True)
class PingResult:
    is_alive: bool
    avg_rtt: float  # seconds
    packet_loss: float  # ratio 0-1


Pinger = Callable[[str], Awaitable[PingResult]]


async def icmp_ping(address: str) -> PingResult:
    """Ping an address three times with icmplib."""
    from icmplib import async_ping  # type: ignore[import-untyped]

    result = await async_ping(address, count=3, timeout=2)
    return PingResult(
        is_alive=bool(result.is_alive),
        avg_rtt=float(result.avg_rtt) / 1000.0,
        packet_loss=float(result.packet_loss),
    )


async def snmp_check(address: str, port: int, community: str) -> PingResult:
    """Check SNMPv2c availability by reading sysUpTime."""
    import pysnmp.hlapi.v3arch.asyncio as hlapi  # type: ignore[import-untyped]

    engine = hlapi.SnmpEngine()
    started = time.perf_counter()
    try:
        target = await hlapi.UdpTransportTarget.create(
            (address, port), timeout=2, retries=0
        )
        indication, error_status, _, var_binds = await hlapi.get_cmd(
            engine,
            hlapi.CommunityData(community, mpModel=1),
            target,
            hlapi.ContextData(),
            hlapi.ObjectType(hlapi.ObjectIdentity("1.3.6.1.2.1.1.3.0")),
        )
    finally:
        engine.close_dispatcher()
    if indication or error_status or not var_binds:
        raise OSError("SNMP availability check failed")
    return PingResult(
        is_alive=True,
        avg_rtt=time.perf_counter() - started,
        packet_loss=0.0,
    )


async def routeros_api_check(
    address: str,
    port: int,
    username: str,
    password: str,
    *,
    verify_tls: bool,
) -> PingResult:
    """Check RouterOS REST API availability over HTTPS."""
    host = f"[{address}]" if ":" in address else address
    started = time.perf_counter()
    async with httpx.AsyncClient(
        verify=verify_tls, timeout=5.0
    ) as client:
        response = await client.get(
            f"https://{host}:{port}/rest/system/resource",
            auth=(username, password),
        )
        response.raise_for_status()
    return PingResult(
        is_alive=True,
        avg_rtt=time.perf_counter() - started,
        packet_loss=0.0,
    )


async def configured_check(device: Device) -> PingResult:
    profile = device.credential_profile
    if profile is None:
        raise RuntimeError("device check requires a credential profile")
    secret = decrypt_secret(profile.secret_ciphertext)
    if (
        device.check_type == DeviceCheckType.SNMP
        and profile.credential_type == CredentialType.SNMP_V2C
    ):
        return await snmp_check(str(device.mgmt_ip), profile.port, secret)
    if (
        device.check_type == DeviceCheckType.ROUTEROS_API
        and profile.credential_type == CredentialType.ROUTEROS_API
        and profile.username
    ):
        return await routeros_api_check(
            str(device.mgmt_ip),
            profile.port,
            profile.username,
            secret,
            verify_tls=profile.verify_tls,
        )
    raise RuntimeError("credential profile type does not match device check type")


async def list_poll_targets(session: AsyncSession) -> list[Device]:
    """Active devices with their sites and check credentials eagerly loaded."""
    rows = await session.scalars(
        select(Device)
        .where(Device.is_active.is_(True))
        .options(
            selectinload(Device.site),
            selectinload(Device.credential_profile),
        )
        .order_by(Device.id)
    )
    return list(rows)


def _publish(device: Device, result: PingResult) -> None:
    site_code = device.site.code
    DEVICE_UP.labels(device.name, site_code).set(1 if result.is_alive else 0)
    if result.is_alive:
        latency = result.avg_rtt if math.isfinite(result.avg_rtt) else NO_SAMPLE
        PING_LATENCY.labels(device.name, site_code).set(latency)
        PING_PACKET_LOSS.labels(device.name, site_code).set(result.packet_loss)
    else:
        PING_LATENCY.labels(device.name, site_code).set(NO_SAMPLE)
        PING_PACKET_LOSS.labels(device.name, site_code).set(1.0)


async def poll_device(
    session: AsyncSession,
    device: Device,
    pinger: Pinger = icmp_ping,
    *,
    now: datetime | None = None,
) -> PingResult:
    """Run one configured check, update metrics and `last_seen_at`."""
    try:
        if device.check_type == DeviceCheckType.PING_ONLY:
            result = await pinger(str(device.mgmt_ip))
        else:
            result = await configured_check(device)
    except Exception as exc:  # noqa: BLE001 - one bad device must not stop the cycle
        logger.warning(
            "Device check error for %s (%s): %s",
            device.name,
            device.mgmt_ip,
            type(exc).__name__,
        )
        result = PingResult(is_alive=False, avg_rtt=NO_SAMPLE, packet_loss=1.0)

    _publish(device, result)

    if result.is_alive:
        device.last_seen_at = now or datetime.now(UTC)
        await session.commit()
        logger.debug(
            "Device check ok: %s rtt=%.1f ms loss=%.0f%%",
            device.name,
            result.avg_rtt * 1000,
            result.packet_loss * 100,
        )
    else:
        logger.info("Device check failed: %s (%s)", device.name, device.mgmt_ip)

    return result


async def poll_due_devices(
    session: AsyncSession,
    pinger: Pinger = icmp_ping,
    *,
    last_polled: dict[int, float] | None = None,
    now_monotonic: float | None = None,
    now: datetime | None = None,
) -> list[int]:
    """Poll devices whose interval elapsed. Returns the polled device ids."""
    last_polled = {} if last_polled is None else last_polled
    current = time.monotonic() if now_monotonic is None else now_monotonic

    polled: list[int] = []
    for device in await list_poll_targets(session):
        previous = last_polled.get(device.id)
        if previous is not None and current - previous < device.poll_interval_seconds:
            continue
        await poll_device(session, device, pinger, now=now)
        last_polled[device.id] = current
        polled.append(device.id)
    return polled


async def run_poller(
    *,
    tick_seconds: float | None = None,
    pinger: Pinger = icmp_ping,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> None:
    """Poll forever, checking for newly added devices every tick."""
    tick = tick_seconds or float(
        os.getenv("WORKER_TICK_SECONDS", str(DEFAULT_TICK_SECONDS))
    )
    last_polled: dict[int, float] = {}
    logger.info("Poller started (tick=%.1fs)", tick)

    while True:
        try:
            async with session_factory() as session:
                polled = await poll_due_devices(
                    session, pinger, last_polled=last_polled
                )
            if polled:
                logger.info("Polled %d device(s): %s", len(polled), polled)
        except Exception:  # keep the worker alive across DB/network blips
            logger.exception("Poll cycle failed")
        await asyncio.sleep(tick)


def main() -> None:
    port = int(os.getenv("WORKER_METRICS_PORT", "9101"))
    start_http_server(port)
    logger.info("Worker metrics listening on :%d", port)
    asyncio.run(run_poller())


if __name__ == "__main__":
    main()
