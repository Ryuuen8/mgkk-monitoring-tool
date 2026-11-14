"""Optional Cisco IOS-XE RESTCONF collection.

RESTCONF is used only when a Cisco device is configured with the ``restconf``
check type.  SNMP remains the default and reuses the shared collector.
"""

import asyncio
import logging
import time
from typing import Any

import httpx

from app.collectors.base import (
    CollectionResult,
    HealthData,
    InterfaceData,
    NeighborData,
    SystemInfo,
)
from app.models import CredentialType, Device
from app.services.credentials import decrypt_secret

logger = logging.getLogger(__name__)

_HEADERS = {"Accept": "application/yang-data+json"}
MAX_TEXT = 255


class RestconfError(OSError):
    """RESTCONF transport, authentication, or payload error."""


def _base_url(device: Device, port: int) -> str:
    address = str(device.mgmt_ip)
    host = f"[{address}]" if ":" in address else address
    return f"https://{host}:{port}/restconf/data"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered[:MAX_TEXT] or None


def _find_list(payload: Any, key: str) -> list[dict[str, Any]]:
    """Find a YANG list in a nested RESTCONF response.

    Cisco responses wrap lists in module-qualified containers, so the exact
    shape varies with the ``depth`` query and IOS-XE release.
    """
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for name, value in payload.items():
        if name == key or name.endswith(f":{key}"):
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                return [value]
    for value in payload.values():
        found = _find_list(value, key)
        if found:
            return found
    return []


def _find_leaf(payload: Any, key: str) -> Any:
    if not isinstance(payload, dict):
        return None
    for name, value in payload.items():
        if name == key or name.endswith(f":{key}"):
            return value
    for value in payload.values():
        found = _find_leaf(value, key)
        if found is not None:
            return found
    return None


async def _get(device: Device, path: str) -> Any:
    profile = device.credential_profile
    if (
        profile is None
        or profile.credential_type is not CredentialType.CISCO_RESTCONF
        or not profile.username
    ):
        raise RestconfError("Cisco RESTCONF requires a RESTCONF credential profile")
    url = f"{_base_url(device, profile.port)}/{path}"
    try:
        async with httpx.AsyncClient(
            verify=profile.verify_tls,
            timeout=10.0,
            auth=(profile.username, decrypt_secret(profile.secret_ciphertext)),
            headers=_HEADERS,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RestconfError(f"{url}: {type(exc).__name__}") from exc


async def _optional_get(device: Device, path: str, label: str) -> Any | None:
    try:
        return await _get(device, path)
    except RestconfError as exc:
        logger.info("RESTCONF %s unavailable for %s: %s", label, device.name, exc)
        return None


def _interfaces(payload: Any) -> dict[int, InterfaceData]:
    rows = _find_list(payload, "interface")
    interfaces: dict[int, InterfaceData] = {}
    for position, row in enumerate(rows, start=1):
        name = _as_text(row.get("name"))
        if name is None:
            continue
        index = _int_or_none(row.get("if-index")) or position
        speed_bits = _int_or_none(row.get("speed"))
        statistics = row.get("statistics")
        stats = statistics if isinstance(statistics, dict) else {}
        interfaces[index] = InterfaceData(
            name=name,
            alias=_as_text(row.get("description")),
            admin=1 if row.get("admin-status") == "if-state-up" else 2,
            oper=1 if row.get("oper-status") == "if-oper-state-ready" else 2,
            speed=(
                round(speed_bits / 1_000_000)
                if speed_bits is not None and speed_bits > 0
                else None
            ),
            in_octets=_int_or_none(stats.get("in-octets")),
            out_octets=_int_or_none(stats.get("out-octets")),
            in_errors=_int_or_none(stats.get("in-errors")),
            out_errors=_int_or_none(stats.get("out-errors")),
            in_discards=_int_or_none(stats.get("in-discards")),
            out_discards=_int_or_none(stats.get("out-discards")),
            crc_errors=_int_or_none(stats.get("in-crc-errors")),
        )
    return interfaces


def _system(payload: Any) -> SystemInfo:
    return SystemInfo(
        name=_as_text(_find_leaf(payload, "hostname")),
        description=_as_text(_find_leaf(payload, "description"))
        or "Cisco IOS-XE RESTCONF",
        uptime_seconds=_int_or_none(_find_leaf(payload, "system-uptime")),
    )


def _health(cpu_payload: Any, memory_payload: Any) -> HealthData:
    cpu = _int_or_none(
        _find_leaf(cpu_payload, "one-minute")
        or _find_leaf(cpu_payload, "five-minutes")
        or _find_leaf(cpu_payload, "five-seconds")
    )
    rows = _find_list(memory_payload, "memory-statistic")
    totals = [_int_or_none(row.get("total-memory")) for row in rows]
    used = [_int_or_none(row.get("used-memory")) for row in rows]
    total_memory = sum(value for value in totals if value is not None)
    used_memory = sum(value for value in used if value is not None)
    return HealthData(
        cpu_usage_percent=float(cpu) if cpu is not None else None,
        memory_total_bytes=total_memory or None,
        memory_used_bytes=used_memory or None,
    )


def _neighbors(cdp_payload: Any | None, lldp_payload: Any | None) -> list[NeighborData]:
    neighbors: dict[tuple[str, str, str, str], NeighborData] = {}
    for row in _find_list(cdp_payload, "cdp-neighbor-detail"):
        local = _as_text(row.get("local-interface-name"))
        if local is None:
            continue
        remote = _as_text(row.get("device-name")) or _as_text(
            row.get("device-id")
        )
        neighbor = NeighborData(
            protocol="cdp",
            local_interface=local,
            remote_device=remote,
            remote_interface=_as_text(row.get("port-id")),
            remote_platform=_as_text(
                row.get("platform-name") or row.get("platform")
            ),
            remote_address=_as_text(row.get("ip-address")),
            capabilities=_as_text(row.get("capabilities")),
        )
        neighbors[
            (
                neighbor.protocol,
                neighbor.local_interface,
                neighbor.remote_device or "",
                neighbor.remote_interface or "",
            )
        ] = neighbor
    for row in _find_list(lldp_payload, "lldp-entry"):
        local = _as_text(row.get("local-interface"))
        if local is None:
            continue
        neighbor = NeighborData(
            protocol="lldp",
            local_interface=local,
            remote_device=_as_text(row.get("system-name"))
            or _as_text(row.get("device-id")),
            remote_interface=_as_text(row.get("port-id")),
            remote_platform=_as_text(row.get("system-description")),
            remote_address=_as_text(row.get("management-address")),
            capabilities=_as_text(row.get("capabilities")),
        )
        neighbors[
            (
                neighbor.protocol,
                neighbor.local_interface,
                neighbor.remote_device or "",
                neighbor.remote_interface or "",
            )
        ] = neighbor
    return sorted(
        neighbors.values(),
        key=lambda item: (
            item.local_interface,
            item.protocol,
            item.remote_device or "",
        ),
    )


async def probe_restconf(device: Device) -> float:
    started = time.perf_counter()
    await _get(device, "Cisco-IOS-XE-native:native/hostname")
    return time.perf_counter() - started


async def collect_restconf(device: Device) -> CollectionResult:
    interfaces_payload = await _get(
        device, "Cisco-IOS-XE-interfaces-oper:interfaces/interface"
    )
    hostname_payload, cpu_payload, memory_payload, cdp_payload, lldp_payload = (
        await asyncio.gather(
            _optional_get(
                device, "Cisco-IOS-XE-native:native/hostname", "hostname"
            ),
            _optional_get(
                device,
                "Cisco-IOS-XE-process-cpu-oper:cpu-usage/cpu-utilization",
                "CPU",
            ),
            _optional_get(
                device,
                "Cisco-IOS-XE-memory-oper:memory-statistics/memory-statistic",
                "memory",
            ),
            _optional_get(
                device,
                "Cisco-IOS-XE-cdp-oper:cdp-neighbor-details/cdp-neighbor-detail",
                "CDP neighbors",
            ),
            _optional_get(
                device,
                "Cisco-IOS-XE-lldp-oper:lldp-entries/lldp-entry",
                "LLDP neighbors",
            ),
        )
    )
    interfaces = _interfaces(interfaces_payload)
    return CollectionResult(
        interfaces={
            index: interface.model_dump()
            for index, interface in interfaces.items()
        },
        system=_system(hostname_payload),
        health=_health(cpu_payload, memory_payload),
        neighbors=_neighbors(cdp_payload, lldp_payload),
    )
