import asyncio
import hashlib
import logging
import re
import ssl
import time
from typing import Any, Self

import httpx
from librouteros import async_connect
from librouteros.api import AsyncApi
from librouteros.exceptions import LibRouterosError

from app.collectors.base import (
    BaseCollector,
    CollectionResult,
    HealthData,
    InterfaceData,
    NeighborData,
    SystemInfo,
)
from app.collectors.generic_snmp import GenericSNMPCollector
from app.models import Device, DeviceCheckType
from app.services.credentials import decrypt_secret

logger = logging.getLogger(__name__)
_UPTIME_PART = re.compile(r"(\d+)([wdhms])")
_SPEED = re.compile(r"([\d.]+)\s*(bps|kbps|mbps|gbps|tbps)", re.IGNORECASE)
_NUMBER = re.compile(r"-?[\d.]+")
_VERSION = re.compile(r"(\d+)\.(\d+)")
_WIRELESS_SERIES: dict[tuple[str, str], set[str]] = {}


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _uptime_seconds(value: Any) -> int | None:
    if not isinstance(value, str):
        return _integer(value)
    units = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}
    parts = _UPTIME_PART.findall(value.lower())
    return sum(int(count) * units[unit] for count, unit in parts) if parts else None


def _health_number(entries: list[dict[str, Any]], field: str) -> float | None:
    for item in entries:
        name = str(item.get("name", "")).lower()
        if field not in name:
            continue
        match = _NUMBER.search(str(item.get("value", "")))
        if match:
            try:
                value = float(match.group())
            except ValueError:
                continue
            if field == "voltage" and "mv" in str(item.get("value", "")).lower():
                value /= 1000
            return value
    return None


def _speed_mbps(value: Any) -> int | None:
    match = _SPEED.search(str(value))
    if not match:
        return None
    scale = {"bps": 0.000001, "kbps": 0.001, "mbps": 1, "gbps": 1000, "tbps": 1_000_000}
    return round(float(match.group(1)) * scale[match.group(2).lower()])


def _interface_rows(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    interfaces: dict[int, dict[str, Any]] = {}
    for index, item in enumerate(rows, start=1):
        name = item.get("name")
        if not name:
            continue
        interfaces[index] = {
            "name": name,
            "alias": item.get("comment"),
            "admin": 2 if str(item.get("disabled", "false")).lower() == "true" else 1,
            "oper": 1 if str(item.get("running", "false")).lower() == "true" else 2,
            "speed": _speed_mbps(item.get("speed")),
            "in_octets": _integer(item.get("rx-byte")),
            "out_octets": _integer(item.get("tx-byte")),
            "in_errors": _integer(item.get("rx-error")),
            "out_errors": _integer(item.get("tx-error")),
            "in_discards": _integer(item.get("rx-drop")),
            "out_discards": _integer(item.get("tx-drop")),
        }
    return interfaces


def _wireless_summary(
    rows: list[dict[str, Any]],
) -> dict[str, tuple[int, float | None]]:
    grouped: dict[str, tuple[int, list[float]]] = {}
    for item in rows:
        interface = item.get("interface")
        if not interface:
            continue
        count, signals = grouped.setdefault(str(interface), (0, []))
        grouped[str(interface)] = (count + 1, signals)
        match = _NUMBER.search(str(item.get("signal-strength", "")))
        if match:
            signals.append(float(match.group()))
    return {
        interface: (
            count,
            sum(signals) / len(signals) if signals else None,
        )
        for interface, (count, signals) in grouped.items()
    }


def _routeros_neighbors(rows: list[dict[str, Any]]) -> list[NeighborData]:
    """Normalise RouterOS ``ip/neighbor`` rows without leaking client data."""
    neighbors: dict[tuple[str, str, str], NeighborData] = {}
    for item in rows:
        interface = item.get("interface")
        if not interface:
            continue
        address = item.get("address")
        identity = item.get("identity") or item.get("sys-name")
        mac = item.get("mac-address")
        platform = (
            item.get("platform")
            or item.get("board")
            or item.get("version")
        )
        neighbor = NeighborData(
            protocol="routeros",
            local_interface=str(interface)[:255],
            remote_device=(
                str(identity)[:255]
                if identity
                else (str(address) if address else None)
            ),
            remote_interface=None,
            remote_platform=str(platform)[:255] if platform else None,
            remote_address=str(address or mac) if (address or mac) else None,
            capabilities=(
                str(item["system-caps"]) if item.get("system-caps") else None
            ),
        )
        key = (
            neighbor.local_interface,
            neighbor.remote_device or "",
            neighbor.remote_device or "",
        )
        neighbors[key] = neighbor
    return sorted(
        neighbors.values(),
        key=lambda item: (
            item.local_interface,
            item.remote_device or "",
        ),
    )


def _resource_fields(device: Device, resource: dict[str, Any]) -> None:
    device.snmp_system_name = str(resource.get("board-name") or device.name)[:255]
    device.snmp_system_description = " ".join(
        str(value) for value in (resource.get("board-name"), resource.get("version")) if value
    )[:4000]
    device.uptime_seconds = _uptime_seconds(resource.get("uptime"))
    device.cpu_usage_percent = _number_float(resource.get("cpu-load"))
    device.memory_total_bytes = _integer(resource.get("total-memory"))
    free_memory = _integer(resource.get("free-memory"))
    device.memory_used_bytes = (
        max(device.memory_total_bytes - free_memory, 0)
        if device.memory_total_bytes is not None and free_memory is not None
        else None
    )
    device.disk_total_bytes = _integer(resource.get("total-hdd-space"))
    free_disk = _integer(resource.get("free-hdd-space"))
    device.disk_used_bytes = (
        max(device.disk_total_bytes - free_disk, 0)
        if device.disk_total_bytes is not None and free_disk is not None
        else None
    )


def _number_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _credential(device: Device) -> tuple[str, str, int, bool]:
    profile = device.credential_profile
    if profile is None or not profile.username:
        raise RuntimeError("MikroTik collector requires a RouterOS API profile")
    return (
        profile.username,
        decrypt_secret(profile.secret_ciphertext),
        profile.port,
        profile.verify_tls,
    )


def _version_tuple(value: str | None) -> tuple[int, int] | None:
    match = _VERSION.search(value or "")
    return (int(match.group(1)), int(match.group(2))) if match else None


async def _connect_binary_credentials(
    address: str,
    port: int,
    username: str,
    password: str,
    verify_tls: bool,
    os_version: str | None = None,
) -> AsyncApi:
    tls = None
    if port == 8729:
        tls = ssl.create_default_context()
        if not verify_tls:
            tls.check_hostname = False
            tls.verify_mode = ssl.CERT_NONE
    kwargs: dict[str, Any] = {
        "host": address,
        "username": username,
        "password": password,
        "port": port,
        "timeout": 5,
        "ssl_wrapper": tls,
    }
    version = _version_tuple(os_version)
    if version is not None and version[0] == 6 and version[1] < 43:
        from librouteros.login import token

        kwargs["login_method"] = token
    try:
        return await async_connect(**kwargs)
    except LibRouterosError:
        if version is not None or "login_method" in kwargs:
            raise
        from librouteros.login import token

        kwargs["login_method"] = token
        return await async_connect(**kwargs)


async def _binary_connect(device: Device) -> AsyncApi:
    username, password, configured_port, verify_tls = _credential(device)
    port = configured_port if configured_port in {8728, 8729} else 8729
    return await _connect_binary_credentials(
        str(device.mgmt_ip),
        port,
        username,
        password,
        verify_tls,
        device.os_version,
    )


async def _binary_rows(api: AsyncApi, path: str) -> list[dict[str, Any]]:
    parts = tuple(part for part in path.split("/") if part)
    return [dict(row) async for row in api.path(*parts)]


async def _rest_get(
    client: httpx.AsyncClient, base_url: str, endpoint: str
) -> Any:
    response = await client.get(f"{base_url}/rest/{endpoint}")
    response.raise_for_status()
    return response.json()


async def _collect_rest(device: Device) -> CollectionResult:
    username, password, port, verify_tls = _credential(device)
    address = str(device.mgmt_ip)
    host = f"[{address}]" if ":" in address else address
    base_url = f"https://{host}:{port}"
    async with httpx.AsyncClient(
        verify=verify_tls, timeout=5.0, auth=(username, password)
    ) as client:
        resource = await _rest_get(client, base_url, "system/resource")
        if not isinstance(resource, dict):
            raise OSError("RouterOS resource response was not an object")
        _resource_fields(device, resource)
        try:
            identity = await _rest_get(client, base_url, "system/identity")
            if isinstance(identity, dict) and identity.get("name"):
                device.snmp_system_name = str(identity["name"])[:255]
        except httpx.HTTPError:
            logger.info("RouterOS identity unavailable for %s", device.name)

        try:
            health = await _rest_get(client, base_url, "system/health")
            health_rows = health if isinstance(health, list) else []
            device.temperature_celsius = _health_number(health_rows, "temperature")
            device.voltage_volts = _health_number(health_rows, "voltage")
        except httpx.HTTPError:
            logger.info("RouterOS health data unavailable for %s", device.name)
            device.temperature_celsius = None
            device.voltage_volts = None

        raw_interfaces = await _rest_get(client, base_url, "interface")
        interfaces = _interface_rows(
            [row for row in raw_interfaces if isinstance(row, dict)]
            if isinstance(raw_interfaces, list)
            else []
        )
        snapshots: dict[str, list[dict[str, Any]]] = {}
        for endpoint, field in (
            ("ip/dhcp-server/lease", "dhcp_lease_count"),
            ("ip/arp", "arp_entry_count"),
        ):
            try:
                rows = await _rest_get(client, base_url, endpoint)
                setattr(device, field, len(rows) if isinstance(rows, list) else 0)
                snapshots[
                    "dhcp_leases" if field == "dhcp_lease_count" else "arp_entries"
                ] = (
                    [dict(row) for row in rows if isinstance(row, dict)]
                    if isinstance(rows, list)
                    else []
                )
            except httpx.HTTPError:
                logger.info("RouterOS %s data unavailable for %s", endpoint, device.name)
                setattr(device, field, None)

        try:
            wireless = await _rest_get(
                client, base_url, "interface/wireless/registration-table"
            )
        except httpx.HTTPError:
            try:
                wireless = await _rest_get(
                    client, base_url, "interface/wifi/registration-table"
                )
            except httpx.HTTPError:
                wireless = []
                logger.info("RouterOS wireless data unavailable for %s", device.name)
        _publish_wireless(device, wireless)
        snapshots["wireless_clients"] = [
            {
                "interface": interface,
                "client_count": count,
                "avg_signal_dbm": signal,
            }
            for interface, (count, signal) in _wireless_summary(
                [row for row in wireless if isinstance(row, dict)]
                if isinstance(wireless, list)
                else []
            ).items()
        ]
        try:
            neighbor_rows = await _rest_get(client, base_url, "ip/neighbor")
        except httpx.HTTPError:
            neighbor_rows = []
            logger.info("RouterOS neighbor data unavailable for %s", device.name)
        neighbors = _routeros_neighbors(
            [row for row in neighbor_rows if isinstance(row, dict)]
            if isinstance(neighbor_rows, list)
            else []
        )
        return CollectionResult(
            interfaces=interfaces,
            snapshots=snapshots,
            neighbors=neighbors,
            system=SystemInfo(
                name=device.snmp_system_name,
                description=device.snmp_system_description,
                uptime_seconds=device.uptime_seconds,
            ),
            health=HealthData(
                cpu_usage_percent=device.cpu_usage_percent,
                memory_total_bytes=device.memory_total_bytes,
                memory_used_bytes=device.memory_used_bytes,
                disk_total_bytes=device.disk_total_bytes,
                disk_used_bytes=device.disk_used_bytes,
                temperature_celsius=device.temperature_celsius,
                voltage_volts=device.voltage_volts,
            ),
        )


class _BinaryApi:
    def __init__(
        self, address: str, port: int, username: str, password: str, verify_tls: bool
    ) -> None:
        self.address = address
        self.port = port
        self.username = username
        self.password = password
        self.verify_tls = verify_tls
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self._authenticated = False

    @staticmethod
    def _encode_length(length: int) -> bytes:
        if length < 0x80:
            return bytes((length,))
        if length < 0x4000:
            return bytes(((length >> 8) | 0x80, length & 0xFF))
        if length < 0x200000:
            return bytes(((length >> 16) | 0xC0, (length >> 8) & 0xFF, length & 0xFF))
        if length < 0x10000000:
            return bytes(
                (
                    (length >> 24) | 0xE0,
                    (length >> 16) & 0xFF,
                    (length >> 8) & 0xFF,
                    length & 0xFF,
                )
            )
        return b"\xF0" + length.to_bytes(4, "big")

    async def _read_length(self) -> int:
        if self.reader is None:
            raise OSError("RouterOS API connection is not open")
        first = (await asyncio.wait_for(self.reader.readexactly(1), 5))[0]
        if first < 0x80:
            return first
        if first < 0xC0:
            tail_byte = (await asyncio.wait_for(self.reader.readexactly(1), 5))[0]
            return ((first & 0x3F) << 8) | tail_byte
        if first < 0xE0:
            tail_bytes = await asyncio.wait_for(self.reader.readexactly(2), 5)
            return ((first & 0x1F) << 16) | int.from_bytes(tail_bytes, "big")
        if first < 0xF0:
            tail_bytes = await asyncio.wait_for(self.reader.readexactly(3), 5)
            return ((first & 0x0F) << 24) | int.from_bytes(tail_bytes, "big")
        if first < 0xF8:
            tail = await asyncio.wait_for(self.reader.readexactly(4), 5)
            return int.from_bytes(tail, "big")
        raise OSError("invalid RouterOS API sentence length")

    async def _read_sentence(self) -> list[str]:
        if self.reader is None:
            raise OSError("RouterOS API connection is not open")
        words: list[str] = []
        while True:
            length = await self._read_length()
            if length == 0:
                return words
            raw = await asyncio.wait_for(self.reader.readexactly(length), 5)
            words.append(raw.decode("utf-8", errors="replace"))

    async def _send_sentence(self, words: list[str]) -> None:
        if self.writer is None:
            raise OSError("RouterOS API connection is not open")
        for word in words:
            raw = word.encode("utf-8")
            self.writer.write(self._encode_length(len(raw)) + raw)
        self.writer.write(b"\x00")
        await self.writer.drain()

    async def _request(self, words: list[str]) -> list[dict[str, str]]:
        await self._send_sentence(words)
        rows: list[dict[str, str]] = []
        error: str | None = None
        while True:
            sentence = await self._read_sentence()
            if not sentence:
                continue
            kind = sentence[0]
            row = {
                pair[1:].split("=", 1)[0]: pair[1:].split("=", 1)[1]
                for pair in sentence[1:]
                if pair.startswith("=") and "=" in pair[1:]
            }
            if kind == "!re":
                rows.append(row)
            elif kind == "!trap":
                error = row.get("message", "RouterOS API command failed")
            elif kind == "!done":
                if error:
                    raise OSError(error)
                challenge = row.get("ret")
                if challenge and words[0] == "/login":
                    response = hashlib.md5(
                        b"\x00" + self.password.encode() + bytes.fromhex(challenge),
                        usedforsecurity=False,
                    ).hexdigest()
                    return await self._request(
                        [
                            "/login",
                            f"=name={self.username}",
                            f"=response=00{response}",
                        ]
                    )
                if words[0] == "/login":
                    self._authenticated = True
                return rows

    async def __aenter__(self) -> Self:
        tls = None
        if self.port == 8729:
            tls = ssl.create_default_context()
            if not self.verify_tls:
                tls.check_hostname = False
                tls.verify_mode = ssl.CERT_NONE
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(self.address, self.port, ssl=tls), 5
        )
        try:
            await self._request(["/login"])
        except OSError:
            if self._authenticated:
                raise
        if not self._authenticated:
            await self._request(
                ["/login", f"=name={self.username}", f"=password={self.password}"]
            )
        if not self._authenticated:
            raise OSError("RouterOS API authentication did not complete")
        return self

    async def __aexit__(self, *_: object) -> None:
        if self.writer is not None:
            self.writer.close()
            await self.writer.wait_closed()

    async def command(self, path: str) -> list[dict[str, str]]:
        return await self._request([path])


async def _collect_binary(device: Device) -> CollectionResult:
    client = await _binary_connect(device)
    try:
        resource_rows = await _binary_rows(client, "system/resource")
        if not resource_rows:
            raise OSError("RouterOS resource response was empty")
        resource = resource_rows[0]
        _resource_fields(device, resource)
        try:
            identity = await _binary_rows(client, "system/identity")
            if identity and identity[0].get("name"):
                device.snmp_system_name = identity[0]["name"][:255]
        except (LibRouterosError, OSError):
            logger.info("RouterOS identity unavailable for %s", device.name)

        try:
            health = await _binary_rows(client, "system/health")
            device.temperature_celsius = _health_number(health, "temperature")
            device.voltage_volts = _health_number(health, "voltage")
        except (LibRouterosError, OSError):
            logger.info("RouterOS health data unavailable for %s", device.name)
            device.temperature_celsius = None
            device.voltage_volts = None

        interface_rows = await _binary_rows(client, "interface")
        interfaces = _interface_rows(interface_rows)
        snapshots: dict[str, list[dict[str, Any]]] = {}
        for path, field in (
            ("ip/dhcp-server/lease", "dhcp_lease_count"),
            ("ip/arp", "arp_entry_count"),
        ):
            try:
                rows = await _binary_rows(client, path)
                setattr(device, field, len(rows))
                snapshots[
                    "dhcp_leases" if field == "dhcp_lease_count" else "arp_entries"
                ] = rows
            except (LibRouterosError, OSError):
                logger.info("RouterOS %s data unavailable for %s", path, device.name)
                setattr(device, field, None)
        try:
            wireless = await _binary_rows(
                client, "interface/wireless/registration-table"
            )
        except (LibRouterosError, OSError):
            try:
                wireless = await _binary_rows(
                    client, "interface/wifi/registration-table"
                )
            except (LibRouterosError, OSError):
                wireless = []
        _publish_wireless(device, wireless)
        snapshots["wireless_clients"] = [
            {
                "interface": interface,
                "client_count": count,
                "avg_signal_dbm": signal,
            }
            for interface, (count, signal) in _wireless_summary(wireless).items()
        ]
        try:
            neighbor_rows = await _binary_rows(client, "ip/neighbor")
        except (LibRouterosError, OSError):
            neighbor_rows = []
            logger.info("RouterOS neighbor data unavailable for %s", device.name)
        return CollectionResult(
            interfaces=interfaces,
            snapshots=snapshots,
            neighbors=_routeros_neighbors(neighbor_rows),
            system=SystemInfo(
                name=device.snmp_system_name,
                description=device.snmp_system_description,
                uptime_seconds=device.uptime_seconds,
            ),
            health=HealthData(
                cpu_usage_percent=device.cpu_usage_percent,
                memory_total_bytes=device.memory_total_bytes,
                memory_used_bytes=device.memory_used_bytes,
                disk_total_bytes=device.disk_total_bytes,
                disk_used_bytes=device.disk_used_bytes,
                temperature_celsius=device.temperature_celsius,
                voltage_volts=device.voltage_volts,
            ),
        )
    finally:
        await client.close()


async def _collect_mikrotik_snmp_health(
    device: Device, fallback: HealthData | None
) -> HealthData:
    from app.collectors.generic_snmp.collector import (
        open_target,
        snmp_get,
        snmp_int,
    )

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
    engine, auth, target = await open_target(device)
    try:
        try:
            values = await snmp_get(engine, auth, target, list(core_oids.values()))
        except OSError as exc:
            logger.info(
                "MikroTik resource MIB unavailable for %s: %s",
                device.name,
                type(exc).__name__,
            )
            return fallback or HealthData()
        for oid in optional_oids.values():
            try:
                values.update(await snmp_get(engine, auth, target, [oid]))
            except OSError:
                logger.debug("Optional MikroTik resource OID unavailable on %s", device.name)
    finally:
        engine.close_dispatcher()

    def value(key: str) -> int | None:
        return snmp_int(values.get(core_oids.get(key) or optional_oids[key]))

    memory_total = value("memory_total")
    memory_free = value("memory_free")
    disk_total = value("disk_total")
    disk_free = value("disk_free")
    cpu = value("cpu")
    voltage = value("voltage")
    temperature = value("temperature")
    return HealthData(
        cpu_usage_percent=float(cpu) if cpu is not None else None,
        memory_total_bytes=memory_total,
        memory_used_bytes=(
            max(memory_total - memory_free, 0)
            if memory_total is not None and memory_free is not None
            else None
        ),
        disk_total_bytes=disk_total,
        disk_used_bytes=(
            max(disk_total - disk_free, 0)
            if disk_total is not None and disk_free is not None
            else None
        ),
        temperature_celsius=float(temperature) if temperature is not None else None,
        voltage_volts=voltage / 10 if voltage is not None else None,
    )


def _publish_wireless(device: Device, rows: Any) -> None:
    from app.worker import (
        MIKROTIK_WIRELESS_CLIENTS,
        MIKROTIK_WIRELESS_SIGNAL_DBM,
    )

    summary = _wireless_summary(
        [row for row in rows if isinstance(row, dict)]
        if isinstance(rows, list)
        else []
    )
    device_labels = (device.name, device.site.code)
    previous = _WIRELESS_SERIES.get(device_labels, set())
    current = {interface[:255] for interface in summary}
    for interface in previous - current:
        labels = (device.name, interface, device.site.code)
        MIKROTIK_WIRELESS_CLIENTS.remove(*labels)
        MIKROTIK_WIRELESS_SIGNAL_DBM.remove(*labels)
    _WIRELESS_SERIES[device_labels] = current
    for interface, (count, signal) in summary.items():
        labels = (device.name, interface[:255], device.site.code)
        MIKROTIK_WIRELESS_CLIENTS.labels(*labels).set(count)
        MIKROTIK_WIRELESS_SIGNAL_DBM.labels(*labels).set(
            signal if signal is not None else float("nan")
        )


async def probe_routeros_api(
    address: str,
    port: int,
    username: str,
    password: str,
    *,
    verify_tls: bool,
) -> float:
    started = time.perf_counter()
    host = f"[{address}]" if ":" in address else address
    try:
        if port not in {8728, 8729}:
            async with httpx.AsyncClient(
                verify=verify_tls, timeout=5.0
            ) as client:
                response = await client.get(
                    f"https://{host}:{port}/rest/system/resource",
                    auth=(username, password),
                )
                response.raise_for_status()
                return time.perf_counter() - started
    except httpx.HTTPError:
        pass

    binary_port = port if port in {8728, 8729} else 8729
    client = await _connect_binary_credentials(
        address, binary_port, username, password, verify_tls
    )
    try:
        await _binary_rows(client, "system/resource")
    finally:
        await client.close()
    return time.perf_counter() - started


class MikroTikCollector(BaseCollector):
    async def collect(self, device: Device) -> CollectionResult:
        if device.check_type is DeviceCheckType.SNMP:
            shared = await GenericSNMPCollector().collect(device)
            health = await _collect_mikrotik_snmp_health(device, shared.health)
            return CollectionResult(
                interfaces=shared.interfaces,
                system=shared.system,
                health=health,
                neighbors=shared.neighbors,
                snapshots=shared.snapshots,
            )
        if device.check_type is DeviceCheckType.ROUTEROS_API:
            return await self._collect_routeros(device)
        raise ValueError("the MikroTik collector requires SNMP or RouterOS API")

    async def collect_system(self, device: Device) -> SystemInfo:
        if device.check_type is DeviceCheckType.SNMP:
            return await GenericSNMPCollector().collect_system(device)
        result = await self._collect_routeros(device)
        if result.system is None:
            raise RuntimeError("RouterOS collector returned no system data")
        return result.system

    async def collect_interfaces(self, device: Device) -> dict[int, InterfaceData]:
        if device.check_type is DeviceCheckType.SNMP:
            return await GenericSNMPCollector().collect_interfaces(device)
        result = await self._collect_routeros(device)
        return {
            index: InterfaceData.model_validate(row)
            for index, row in result.interfaces.items()
        }

    async def collect_health(self, device: Device) -> HealthData:
        if device.check_type is DeviceCheckType.SNMP:
            standard = await GenericSNMPCollector().collect_health(device)
            return await _collect_mikrotik_snmp_health(device, standard)
        result = await self._collect_routeros(device)
        if result.health is None:
            raise RuntimeError("RouterOS collector returned no health data")
        return result.health

    async def discover_neighbors(self, device: Device) -> list[NeighborData]:
        if device.check_type is DeviceCheckType.SNMP:
            return await GenericSNMPCollector().discover_neighbors(device)
        result = await self._collect_routeros(device)
        return result.neighbors

    @staticmethod
    async def _collect_routeros(device: Device) -> CollectionResult:
        profile = device.credential_profile
        if profile is None:
            raise RuntimeError("MikroTik collector requires a RouterOS API profile")
        version = _version_tuple(device.os_version)
        if profile.port in {8728, 8729} or (
            version is not None and version < (7, 1)
        ):
            return await _collect_binary(device)
        if version is not None and version >= (7, 1):
            return await _collect_rest(device)
        try:
            return await _collect_rest(device)
        except httpx.HTTPError as exc:
            logger.info(
                "RouterOS REST unavailable for %s; trying binary API (%s)",
                device.name,
                type(exc).__name__,
            )
        except (LibRouterosError, OSError, ValueError) as exc:
            logger.info(
                "RouterOS REST data unavailable for %s; trying binary API (%s)",
                device.name,
                type(exc).__name__,
            )
        return await _collect_binary(device)
