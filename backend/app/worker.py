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
from typing import Any

from dotenv import load_dotenv
from prometheus_client import Counter, Gauge, start_http_server
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.collectors import get_collector
from app.db.session import SessionLocal
from app.models import (
    CollectorType,
    CredentialType,
    Device,
    DeviceCheckType,
    NetworkInterface,
)
from app.models.credentials import SnmpAuthProtocol, SnmpPrivacyProtocol
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
INTERFACE_IN_BYTES = Counter(
    "interface_in_bytes_total",
    "Total inbound interface bytes observed by the poller",
    ("device", "interface", "site"),
)
INTERFACE_OUT_BYTES = Counter(
    "interface_out_bytes_total",
    "Total outbound interface bytes observed by the poller",
    ("device", "interface", "site"),
)
INTERFACE_IN_ERRORS = Counter(
    "interface_in_errors_total",
    "Total inbound interface errors observed by the poller",
    ("device", "interface", "site"),
)
INTERFACE_OUT_ERRORS = Counter(
    "interface_out_errors_total",
    "Total outbound interface errors observed by the poller",
    ("device", "interface", "site"),
)
INTERFACE_IN_DISCARDS = Counter(
    "interface_in_discards_total",
    "Total inbound interface discards observed by the poller",
    ("device", "interface", "site"),
)
INTERFACE_OUT_DISCARDS = Counter(
    "interface_out_discards_total",
    "Total outbound interface discards observed by the poller",
    ("device", "interface", "site"),
)
INTERFACE_IN_LINK_UTILIZATION = Gauge(
    "interface_in_link_utilization_ratio",
    "Inbound interface traffic as a fraction of configured link speed",
    ("device", "interface", "site"),
)
INTERFACE_OUT_LINK_UTILIZATION = Gauge(
    "interface_out_link_utilization_ratio",
    "Outbound interface traffic as a fraction of configured link speed",
    ("device", "interface", "site"),
)
DEVICE_CPU_USAGE = Gauge(
    "device_cpu_usage_percent",
    "CPU utilization percentage",
    ("device", "site"),
)
DEVICE_MEMORY_USAGE = Gauge(
    "device_memory_usage_bytes",
    "Used memory in bytes",
    ("device", "site"),
)
DEVICE_DISK_USAGE = Gauge(
    "device_disk_usage_bytes",
    "Used disk space in bytes",
    ("device", "site"),
)
DEVICE_TEMPERATURE = Gauge(
    "device_temperature_celsius",
    "Device temperature in degrees Celsius",
    ("device", "site"),
)
DEVICE_VOLTAGE = Gauge(
    "device_voltage_volts",
    "Device voltage in volts",
    ("device", "site"),
)
MIKROTIK_DHCP_LEASES = Gauge(
    "mikrotik_dhcp_lease_count",
    "Number of DHCP leases",
    ("device", "site"),
)
MIKROTIK_ARP_ENTRIES = Gauge(
    "mikrotik_arp_entry_count",
    "Number of ARP entries",
    ("device", "site"),
)
MIKROTIK_WIRELESS_CLIENTS = Gauge(
    "mikrotik_wireless_client_count",
    "Wireless clients associated with an interface",
    ("device", "interface", "site"),
)
MIKROTIK_WIRELESS_SIGNAL_DBM = Gauge(
    "mikrotik_wireless_signal_strength_dbm",
    "Average wireless client signal strength in dBm",
    ("device", "interface", "site"),
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


async def _snmp_profile_check(device: Device) -> PingResult:
    import pysnmp.hlapi.v3arch.asyncio as hlapi  # type: ignore[import-untyped]

    profile = device.credential_profile
    if profile is None:
        raise RuntimeError("SNMP device has no credential profile")
    engine = hlapi.SnmpEngine()
    started = time.perf_counter()
    try:
        target = await hlapi.UdpTransportTarget.create(
            (str(device.mgmt_ip), profile.port), timeout=2, retries=0
        )
        indication, error_status, _, var_binds = await hlapi.get_cmd(
            engine,
            _snmp_auth(profile),
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


def _snmp_auth(profile: Any) -> Any:
    import pysnmp.hlapi.v3arch.asyncio as hlapi  # type: ignore[import-untyped]

    if profile.credential_type == CredentialType.SNMP_V2C:
        return hlapi.CommunityData(decrypt_secret(profile.secret_ciphertext), mpModel=1)
    if profile.credential_type != CredentialType.SNMP_V3 or not profile.username:
        raise RuntimeError("unsupported SNMP credential profile")

    auth_protocols = {
        SnmpAuthProtocol.SHA: hlapi.usmHMACSHAAuthProtocol,
        SnmpAuthProtocol.SHA256: hlapi.usmHMAC192SHA256AuthProtocol,
    }
    privacy_protocols = {
        SnmpPrivacyProtocol.NONE: hlapi.usmNoPrivProtocol,
        SnmpPrivacyProtocol.AES128: hlapi.usmAesCfb128Protocol,
    }
    auth_secret = decrypt_secret(profile.secret_ciphertext)
    privacy_secret = (
        decrypt_secret(profile.privacy_secret_ciphertext)
        if profile.privacy_secret_ciphertext
        else None
    )
    return hlapi.UsmUserData(
        profile.username,
        authKey=auth_secret,
        privKey=privacy_secret,
        authProtocol=auth_protocols[profile.auth_protocol],
        privProtocol=privacy_protocols[profile.privacy_protocol],
    )


async def _snmp_get(
    engine: Any, auth: Any, target: Any, oids: list[str]
) -> dict[str, Any]:
    import pysnmp.hlapi.v3arch.asyncio as hlapi  # type: ignore[import-untyped]

    indication, error_status, _, var_binds = await hlapi.get_cmd(
        engine,
        auth,
        target,
        hlapi.ContextData(),
        *(hlapi.ObjectType(hlapi.ObjectIdentity(oid)) for oid in oids),
    )
    if indication or error_status:
        raise OSError("SNMP GET failed")
    return {str(name): value for name, value in var_binds}


async def _snmp_walk(engine: Any, auth: Any, target: Any, base_oid: str) -> dict[int, Any]:
    import pysnmp.hlapi.v3arch.asyncio as hlapi  # type: ignore[import-untyped]

    values: dict[int, Any] = {}
    async for indication, error_status, _, var_binds in hlapi.walk_cmd(
        engine,
        auth,
        target,
        hlapi.ContextData(),
        hlapi.ObjectType(hlapi.ObjectIdentity(base_oid)),
        lexicographicMode=False,
    ):
        if indication or error_status:
            raise OSError(f"SNMP walk failed for {base_oid}")
        for name, value in var_binds:
            oid = str(name)
            if not oid.startswith(base_oid + "."):
                continue
            try:
                index = int(oid.rsplit(".", 1)[1])
            except ValueError:
                continue
            values[index] = value
    return values


def _aggregate_host_resources(
    processor_loads: dict[int, Any],
    storage_types: dict[int, Any],
    storage_allocation_units: dict[int, Any],
    storage_sizes: dict[int, Any],
    storage_used: dict[int, Any],
) -> tuple[float | None, int | None, int | None]:
    cpu_values = [
        value
        for raw in processor_loads.values()
        if (value := _snmp_int(raw)) is not None
    ]
    cpu_usage = sum(cpu_values) / len(cpu_values) if cpu_values else None

    memory_total = 0
    memory_used = 0
    memory_found = False
    for index, raw_type in storage_types.items():
        if _snmp_int(raw_type) != 2:  # hrStorageRam
            continue
        allocation_units = _snmp_int(storage_allocation_units.get(index))
        size = _snmp_int(storage_sizes.get(index))
        used = _snmp_int(storage_used.get(index))
        if (
            allocation_units is None
            or size is None
            or used is None
            or allocation_units < 0
            or size < 0
            or used < 0
        ):
            continue
        memory_total += allocation_units * size
        memory_used += allocation_units * used
        memory_found = True

    if not memory_found:
        return cpu_usage, None, None
    return cpu_usage, memory_total, memory_used


async def _poll_host_resources(
    engine: Any, auth: Any, target: Any, device_name: str
) -> tuple[float | None, int | None, int | None]:
    processor_load_oid = "1.3.6.1.2.1.25.3.3.1.2"
    storage_oids = {
        "type": "1.3.6.1.2.1.25.2.3.1.2",
        "allocation_units": "1.3.6.1.2.1.25.2.3.1.4",
        "size": "1.3.6.1.2.1.25.2.3.1.5",
        "used": "1.3.6.1.2.1.25.2.3.1.6",
    }

    try:
        processor_loads = await _snmp_walk(engine, auth, target, processor_load_oid)
    except OSError as exc:
        logger.warning(
            "Standard SNMP CPU metrics unavailable for %s: %s",
            device_name,
            type(exc).__name__,
        )
        processor_loads = {}

    try:
        storage = {
            name: await _snmp_walk(engine, auth, target, oid)
            for name, oid in storage_oids.items()
        }
    except OSError as exc:
        logger.warning(
            "Standard SNMP memory metrics unavailable for %s: %s",
            device_name,
            type(exc).__name__,
        )
        storage = {}

    return _aggregate_host_resources(
        processor_loads,
        storage.get("type", {}),
        storage.get("allocation_units", {}),
        storage.get("size", {}),
        storage.get("used", {}),
    )


def _snmp_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _counter_delta(current: int, previous: Any, *, bits: int = 64) -> int:
    if previous is None:
        return 0
    prior = int(previous)
    if current >= prior:
        return current - prior
    maximum = (1 << bits) - 1
    if prior >= maximum * 9 // 10 and current <= maximum // 10:
        return maximum - prior + current + 1
    return current


def _remove_interface_metrics(device: Device, interface_name: str) -> None:
    labels = (device.name, interface_name, device.site.code)
    for metric in (
        INTERFACE_IN_BYTES,
        INTERFACE_OUT_BYTES,
        INTERFACE_IN_ERRORS,
        INTERFACE_OUT_ERRORS,
        INTERFACE_IN_DISCARDS,
        INTERFACE_OUT_DISCARDS,
        INTERFACE_IN_LINK_UTILIZATION,
        INTERFACE_OUT_LINK_UTILIZATION,
    ):
        metric.remove(*labels)


async def poll_snmp_telemetry(device: Device) -> dict[int, dict[str, Any]]:
    """Read system, interface, and resource data with SNMP."""
    import pysnmp.hlapi.v3arch.asyncio as hlapi  # type: ignore[import-untyped]

    profile = device.credential_profile
    if profile is None:
        raise RuntimeError("SNMP device has no credential profile")
    engine = hlapi.SnmpEngine()
    try:
        target = await hlapi.UdpTransportTarget.create(
            (str(device.mgmt_ip), profile.port), timeout=2, retries=0
        )
        auth = _snmp_auth(profile)
        system_oids = [
            "1.3.6.1.2.1.1.1.0",  # sysDescr
            "1.3.6.1.2.1.1.3.0",  # sysUpTime
            "1.3.6.1.2.1.1.5.0",  # sysName
        ]
        system = await _snmp_get(engine, auth, target, system_oids)
        device.snmp_system_description = str(system["1.3.6.1.2.1.1.1.0"])
        device.snmp_system_name = str(system["1.3.6.1.2.1.1.5.0"])
        ticks = _snmp_int(system["1.3.6.1.2.1.1.3.0"])
        device.uptime_seconds = ticks // 100 if ticks is not None else None
        if device.collector is CollectorType.MIKROTIK:
            await _poll_mikrotik_snmp_resources(engine, auth, target, device)
        else:
            (
                device.cpu_usage_percent,
                device.memory_total_bytes,
                device.memory_used_bytes,
            ) = await _poll_host_resources(engine, auth, target, device.name)

        columns = {
            "name": "1.3.6.1.2.1.31.1.1.1.1",
            "description": "1.3.6.1.2.1.2.2.1.2",
            "alias": "1.3.6.1.2.1.31.1.1.1.18",
            "speed": "1.3.6.1.2.1.31.1.1.1.15",
            "in_octets": "1.3.6.1.2.1.31.1.1.1.6",
            "out_octets": "1.3.6.1.2.1.31.1.1.1.10",
            "in_errors": "1.3.6.1.2.1.2.2.1.14",
            "out_errors": "1.3.6.1.2.1.2.2.1.20",
            "in_discards": "1.3.6.1.2.1.2.2.1.13",
            "out_discards": "1.3.6.1.2.1.2.2.1.19",
            "admin": "1.3.6.1.2.1.2.2.1.7",
            "oper": "1.3.6.1.2.1.2.2.1.8",
        }
        walks = {
            name: await _snmp_walk(engine, auth, target, oid)
            for name, oid in columns.items()
        }
        return {
            index: {
                **{name: table.get(index) for name, table in walks.items()},
                "name": walks["name"].get(index)
                or walks["description"].get(index),
            }
            for index in set(walks["name"]) | set(walks["description"])
        }
    finally:
        engine.close_dispatcher()


async def _poll_mikrotik_snmp_resources(
    engine: Any, auth: Any, target: Any, device: Device
) -> None:
    core_oids = {
        "cpu": "1.3.6.1.4.1.14988.1.1.3.11.0",
        "memory_total": "1.3.6.1.4.1.14988.1.1.3.1.0",
        "memory_free": "1.3.6.1.4.1.14988.1.1.3.2.0",
    }
    optional_oids = {
        "disk_total": "1.3.6.1.4.1.14988.1.1.3.4.0",
        "disk_free": "1.3.6.1.4.1.14988.1.1.3.5.0",
        "voltage": "1.3.6.1.4.1.14988.1.1.3.6.0",
        "temperature": "1.3.6.1.4.1.14988.1.1.3.7.0",
    }
    oids = core_oids | optional_oids
    try:
        values = await _snmp_get(engine, auth, target, list(core_oids.values()))
    except OSError as exc:
        logger.warning(
            "MikroTik resource MIB unavailable for %s; trying HOST-RESOURCES-MIB (%s)",
            device.name,
            type(exc).__name__,
        )
        (
            device.cpu_usage_percent,
            device.memory_total_bytes,
            device.memory_used_bytes,
        ) = await _poll_host_resources(engine, auth, target, device.name)
        return
    try:
        values.update(
            await _snmp_get(engine, auth, target, list(optional_oids.values()))
        )
    except OSError as exc:
        logger.info(
            "MikroTik optional resource MIB values unavailable together for %s; "
            "reading individually (%s)",
            device.name,
            type(exc).__name__,
        )
        for name, oid in optional_oids.items():
            try:
                values.update(await _snmp_get(engine, auth, target, [oid]))
            except OSError:
                logger.info("MikroTik %s MIB value unavailable for %s", name, device.name)

    def value(name: str) -> int | None:
        return _snmp_int(values.get(oids[name]))

    cpu = value("cpu")
    total_memory = value("memory_total")
    free_memory = value("memory_free")
    total_disk = value("disk_total")
    free_disk = value("disk_free")
    voltage = value("voltage")
    device.cpu_usage_percent = float(cpu) if cpu is not None else None
    device.memory_total_bytes = total_memory
    device.memory_used_bytes = (
        max(total_memory - free_memory, 0)
        if total_memory is not None and free_memory is not None
        else None
    )
    device.disk_total_bytes = total_disk
    device.disk_used_bytes = (
        max(total_disk - free_disk, 0)
        if total_disk is not None and free_disk is not None
        else None
    )
    device.voltage_volts = voltage / 10 if voltage is not None else None
    temperature = value("temperature")
    device.temperature_celsius = (
        float(temperature) if temperature is not None else None
    )


async def save_interface_telemetry(
    session: AsyncSession, device: Device, interfaces: dict[int, dict[str, Any]]
) -> None:
    from sqlalchemy import select

    existing_rows = await session.scalars(
        select(NetworkInterface).where(NetworkInterface.device_id == device.id)
    )
    existing = {row.if_index: row for row in existing_rows}
    now = datetime.now(UTC)
    counters = {
        "in_octets": INTERFACE_IN_BYTES,
        "out_octets": INTERFACE_OUT_BYTES,
        "in_errors": INTERFACE_IN_ERRORS,
        "out_errors": INTERFACE_OUT_ERRORS,
        "in_discards": INTERFACE_IN_DISCARDS,
        "out_discards": INTERFACE_OUT_DISCARDS,
    }
    for if_index, data in interfaces.items():
        name = str(data["name"])
        row = existing.get(if_index)
        if row is not None and row.name != name:
            row = next((item for item in existing.values() if item.name == name), None)
            if row is not None:
                if_index = row.if_index
        if row is None:
            row = NetworkInterface(device_id=device.id, if_index=if_index, name=name)
            session.add(row)
        elif row.name != name:
            _remove_interface_metrics(device, row.name)
        row.name = name[:255] or f"if{if_index}"
        row.alias = str(data["alias"])[:255] if data.get("alias") else None
        row.admin_status = _snmp_int(data.get("admin"))
        row.oper_status = _snmp_int(data.get("oper"))
        speed = _snmp_int(data.get("speed"))
        row.link_speed_mbps = speed if speed and speed > 0 else None
        elapsed = (
            (now - row.last_polled_at).total_seconds()
            if row.last_polled_at is not None
            else 0
        )
        deltas: dict[str, int] = {}
        for field, metric in counters.items():
            value = _snmp_int(data.get(field))
            if value is None:
                continue
            previous = getattr(row, f"last_{field}")
            delta = _counter_delta(
                value, previous, bits=64 if field.endswith("octets") else 32
            )
            deltas[field] = delta
            child = metric.labels(device.name, row.name, device.site.code)
            if delta:
                child.inc(delta)
            setattr(row, f"last_{field}", value)

        effective_speed = row.link_speed_override_mbps or row.link_speed_mbps
        if effective_speed and elapsed > 0:
            INTERFACE_IN_LINK_UTILIZATION.labels(
                device.name, row.name, device.site.code
            ).set(
                deltas.get("in_octets", 0) * 8
                / elapsed
                / (effective_speed * 1_000_000)
            )
            INTERFACE_OUT_LINK_UTILIZATION.labels(
                device.name, row.name, device.site.code
            ).set(
                deltas.get("out_octets", 0) * 8
                / elapsed
                / (effective_speed * 1_000_000)
            )
        else:
            INTERFACE_IN_LINK_UTILIZATION.labels(
                device.name, row.name, device.site.code
            ).set(NO_SAMPLE)
            INTERFACE_OUT_LINK_UTILIZATION.labels(
                device.name, row.name, device.site.code
            ).set(NO_SAMPLE)
        row.last_polled_at = now
    for if_index, row in existing.items():
        if if_index not in interfaces:
            _remove_interface_metrics(device, row.name)
            await session.delete(row)
    await session.commit()

async def routeros_api_check(
    address: str,
    port: int,
    username: str,
    password: str,
    *,
    verify_tls: bool,
) -> PingResult:
    """Check RouterOS REST API availability, falling back to the v6 binary API."""
    started = time.perf_counter()
    from app.collectors.mikrotik import probe_routeros_api

    await probe_routeros_api(
        address,
        port,
        username,
        password,
        verify_tls=verify_tls,
    )
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
        device.check_type == DeviceCheckType.SNMP
        and profile.credential_type == CredentialType.SNMP_V3
    ):
        return await _snmp_profile_check(device)
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
        if device.check_type != DeviceCheckType.PING_ONLY:
            try:
                collected = await get_collector(device.collector).collect(device)
                if collected.interfaces:
                    await save_interface_telemetry(
                        session, device, collected.interfaces
                    )
                DEVICE_CPU_USAGE.labels(device.name, device.site.code).set(
                    device.cpu_usage_percent
                    if device.cpu_usage_percent is not None
                    else NO_SAMPLE
                )
                DEVICE_MEMORY_USAGE.labels(device.name, device.site.code).set(
                    device.memory_used_bytes
                    if device.memory_used_bytes is not None
                    else NO_SAMPLE
                )
                DEVICE_DISK_USAGE.labels(device.name, device.site.code).set(
                    device.disk_used_bytes
                    if device.disk_used_bytes is not None
                    else NO_SAMPLE
                )
                DEVICE_TEMPERATURE.labels(device.name, device.site.code).set(
                    device.temperature_celsius
                    if device.temperature_celsius is not None
                    else NO_SAMPLE
                )
                DEVICE_VOLTAGE.labels(device.name, device.site.code).set(
                    device.voltage_volts
                    if device.voltage_volts is not None
                    else NO_SAMPLE
                )
                if device.collector is CollectorType.MIKROTIK:
                    MIKROTIK_DHCP_LEASES.labels(
                        device.name, device.site.code
                    ).set(
                        device.dhcp_lease_count
                        if device.dhcp_lease_count is not None
                        else NO_SAMPLE
                    )
                    MIKROTIK_ARP_ENTRIES.labels(
                        device.name, device.site.code
                    ).set(
                        device.arp_entry_count
                        if device.arp_entry_count is not None
                        else NO_SAMPLE
                    )
            except Exception as exc:  # noqa: BLE001 - telemetry must not stop polling
                await session.rollback()
                logger.warning(
                    "SNMP telemetry error for %s: %s",
                    device.name,
                    type(exc).__name__,
                )
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
