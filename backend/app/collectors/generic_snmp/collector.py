"""Generic SNMP system, IF-MIB, HOST-RESOURCES-MIB, and LLDP polling.

This module is the single shared SNMP implementation.  Vendor collectors
(``mikrotik`` and ``cisco``) import these helpers instead of duplicating MIB
logic.  Vendor OIDs must never be added here.
"""

import logging
from collections.abc import Iterable
from typing import Any

import pysnmp.hlapi.v3arch.asyncio as hlapi
from pysnmp.proto.rfc1902 import OctetString

from app.collectors.base import (
    BaseCollector,
    CollectionResult,
    HealthData,
    InterfaceData,
    NeighborData,
    SystemInfo,
)
from app.models import CredentialType, Device
from app.models.credentials import SnmpAuthProtocol, SnmpPrivacyProtocol
from app.services.credentials import decrypt_secret

logger = logging.getLogger(__name__)

SYSTEM_OIDS = {
    "description": "1.3.6.1.2.1.1.1.0",
    "uptime": "1.3.6.1.2.1.1.3.0",
    "name": "1.3.6.1.2.1.1.5.0",
}

IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
INTERFACE_COLUMNS = {
    "name": IF_NAME,
    "description": "1.3.6.1.2.1.2.2.1.2",
    "alias": "1.3.6.1.2.1.31.1.1.1.18",
    "speed": "1.3.6.1.2.1.31.1.1.1.15",
    "in_octets": "1.3.6.1.2.1.31.1.1.1.6",
    "out_octets": "1.3.6.1.2.1.31.1.1.1.10",
    "in_octets_32": "1.3.6.1.2.1.2.2.1.10",
    "out_octets_32": "1.3.6.1.2.1.2.2.1.16",
    "in_errors": "1.3.6.1.2.1.2.2.1.14",
    "out_errors": "1.3.6.1.2.1.2.2.1.20",
    "in_discards": "1.3.6.1.2.1.2.2.1.13",
    "out_discards": "1.3.6.1.2.1.2.2.1.19",
    "admin": "1.3.6.1.2.1.2.2.1.7",
    "oper": "1.3.6.1.2.1.2.2.1.8",
    "crc_errors": "1.3.6.1.2.1.10.7.2.1.3",
}

HOST_CPU_LOAD = "1.3.6.1.2.1.25.3.3.1.2"
HOST_STORAGE = {
    "type": "1.3.6.1.2.1.25.2.3.1.2",
    "allocation_units": "1.3.6.1.2.1.25.2.3.1.4",
    "size": "1.3.6.1.2.1.25.2.3.1.5",
    "used": "1.3.6.1.2.1.25.2.3.1.6",
}
ENTITY_SENSOR_COLUMNS = {
    "type": "1.3.6.1.2.1.99.1.1.1.1",
    "scale": "1.3.6.1.2.1.99.1.1.1.2",
    "precision": "1.3.6.1.2.1.99.1.1.1.3",
    "value": "1.3.6.1.2.1.99.1.1.1.4",
}

# IEEE 802.1AB LLDP remote table.  The index is
# timeMark.localPortNum.remoteIndex.
LLDP_REM_COLUMNS = {
    "chassis_subtype": "1.0.8802.1.1.2.1.4.1.1.4",
    "chassis_id": "1.0.8802.1.1.2.1.4.1.1.5",
    "port_subtype": "1.0.8802.1.1.2.1.4.1.1.6",
    "port_id": "1.0.8802.1.1.2.1.4.1.1.7",
    "port_description": "1.0.8802.1.1.2.1.4.1.1.8",
    "system_name": "1.0.8802.1.1.2.1.4.1.1.9",
    "system_description": "1.0.8802.1.1.2.1.4.1.1.10",
    "capabilities": "1.0.8802.1.1.2.1.4.1.1.12",
}

_LLDP_CAPABILITIES = (
    "other",
    "repeater",
    "bridge",
    "wlanAccessPoint",
    "router",
    "telephone",
    "docsisCableDevice",
    "stationOnly",
    "cVLAN",
    "sVLAN",
    "twoPortMACRelay",
)

# Compatibility aliases for callers that imported the old private names.
_SYSTEM_OIDS = SYSTEM_OIDS
_INTERFACE_COLUMNS = INTERFACE_COLUMNS
_HOST_CPU_LOAD = HOST_CPU_LOAD
_HOST_STORAGE = HOST_STORAGE
_ENTITY_SENSOR_COLUMNS = ENTITY_SENSOR_COLUMNS


def _auth_for_device(device: Device) -> Any:
    profile = device.credential_profile
    if profile is None:
        raise RuntimeError("SNMP device has no credential profile")
    if profile.credential_type == CredentialType.SNMP_V2C:
        return hlapi.CommunityData(decrypt_secret(profile.secret_ciphertext), mpModel=1)
    if profile.credential_type != CredentialType.SNMP_V3 or not profile.username:
        raise RuntimeError("unsupported SNMP credential profile")

    if profile.auth_protocol is None or profile.privacy_protocol is None:
        raise RuntimeError("SNMP v3 profile is missing security protocols")
    auth_protocols = {
        SnmpAuthProtocol.SHA: hlapi.usmHMACSHAAuthProtocol,
        SnmpAuthProtocol.SHA256: hlapi.usmHMAC192SHA256AuthProtocol,
    }
    privacy_protocols = {
        SnmpPrivacyProtocol.NONE: hlapi.usmNoPrivProtocol,
        SnmpPrivacyProtocol.AES128: hlapi.usmAesCfb128Protocol,
    }
    privacy_secret = (
        decrypt_secret(profile.privacy_secret_ciphertext)
        if profile.privacy_secret_ciphertext
        else None
    )
    return hlapi.UsmUserData(
        profile.username,
        authKey=decrypt_secret(profile.secret_ciphertext),
        privKey=privacy_secret,
        authProtocol=auth_protocols[profile.auth_protocol],
        privProtocol=privacy_protocols[profile.privacy_protocol],
    )


async def open_target(device: Device) -> tuple[Any, Any, Any]:
    """Open one SNMP transport target and return ``(engine, auth, target)``."""
    profile = device.credential_profile
    if profile is None:
        raise RuntimeError("SNMP device has no credential profile")
    engine = hlapi.SnmpEngine()
    try:
        target = await hlapi.UdpTransportTarget.create(
            (str(device.mgmt_ip), profile.port), timeout=2, retries=0
        )
        return engine, _auth_for_device(device), target
    except Exception:
        engine.close_dispatcher()
        raise


async def _open_target(device: Device) -> tuple[Any, Any, Any]:
    """Compatibility seam used by tests and callers that patch the opener."""
    return await open_target(device)


async def snmp_get(
    engine: Any, auth: Any, target: Any, oids: Iterable[str]
) -> dict[str, Any]:
    requested = list(oids)
    indication, error_status, _, var_binds = await hlapi.get_cmd(
        engine,
        auth,
        target,
        hlapi.ContextData(),
        *(hlapi.ObjectType(hlapi.ObjectIdentity(oid)) for oid in requested),
    )
    if indication or error_status:
        raise OSError("SNMP GET failed")
    return {str(name): value for name, value in var_binds}


async def snmp_walk(
    engine: Any, auth: Any, target: Any, base_oid: str
) -> dict[int, Any]:
    """Walk a table whose index is a single integer (for example ifIndex)."""
    values: dict[int, Any] = {}
    for suffix, value in (
        await snmp_walk_raw(engine, auth, target, base_oid)
    ).items():
        try:
            values[int(suffix.rsplit(".", 1)[-1])] = value
        except ValueError:
            continue
    return values


async def snmp_walk_raw(
    engine: Any, auth: Any, target: Any, base_oid: str
) -> dict[str, Any]:
    """Walk a table and key the results by the full OID suffix.

    Multi-part indexes (LLDP, CDP) need the whole suffix, not only its last
    component.
    """
    values: dict[str, Any] = {}
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
        prefix = base_oid + "."
        for name, value in var_binds:
            oid = str(name)
            if oid.startswith(prefix):
                values[oid[len(prefix) :]] = value
    return values


def snmp_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def snmp_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def text_value(value: Any) -> str | None:
    """Render an SNMP value as display text."""
    if value is None:
        return None
    pretty = getattr(value, "prettyPrint", None)
    if callable(pretty):
        rendered = str(pretty())
    else:
        rendered = str(value)
    rendered = rendered.strip()
    return rendered or None


def octet_bytes(value: Any) -> bytes | None:
    if isinstance(value, bytes):
        return value
    if isinstance(value, OctetString):
        return bytes(value.asOctets())
    as_octets = getattr(value, "asOctets", None)
    if callable(as_octets):
        try:
            return bytes(as_octets())
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        if value.startswith("0x"):
            try:
                return bytes.fromhex(value[2:])
            except ValueError:
                return None
        return value.encode("utf-8", errors="replace")
    return None


def decode_address(value: Any) -> str | None:
    raw = octet_bytes(value)
    if not raw:
        return None
    if len(raw) == 4:
        return ".".join(str(octet) for octet in raw)
    if len(raw) == 16:
        return ":".join(f"{raw[index:index + 2].hex()}" for index in range(0, 16, 2))
    return None


def decode_identifier(value: Any, subtype: int | None) -> str | None:
    """Decode an LLDP/CDP identifier; subtype 4 is a MAC address."""
    raw = octet_bytes(value)
    if raw is None:
        return None
    if subtype == 4 and len(raw) == 6:
        return raw.hex(":")
    try:
        rendered = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return raw.hex()
    if rendered and all(character.isprintable() for character in rendered):
        return rendered
    return raw.hex()


def capability_names(value: Any) -> str | None:
    bits = snmp_int(value)
    if bits is None:
        return None
    names = [
        name for bit, name in enumerate(_LLDP_CAPABILITIES) if bits & (1 << bit)
    ]
    return ",".join(names) or None


def _interface_names(
    table: dict[int, Any], fallback_prefix: str
) -> dict[int, str]:
    names: dict[int, str] = {}
    for index, value in table.items():
        rendered = text_value(value)
        names[index] = rendered or f"{fallback_prefix}{index}"
    return names


async def _get(
    engine: Any, auth: Any, target: Any, oids: Iterable[str]
) -> dict[str, Any]:
    """Compatibility seam around :func:`snmp_get`."""
    return await snmp_get(engine, auth, target, oids)


async def _walk(
    engine: Any, auth: Any, target: Any, base_oid: str
) -> dict[int, Any]:
    """Compatibility seam around :func:`snmp_walk`."""
    return await snmp_walk(engine, auth, target, base_oid)


async def _walk_raw(
    engine: Any, auth: Any, target: Any, base_oid: str
) -> dict[str, Any]:
    """Compatibility seam around :func:`snmp_walk_raw`."""
    return await snmp_walk_raw(engine, auth, target, base_oid)


async def poll_system(engine: Any, auth: Any, target: Any) -> SystemInfo:
    values = await _get(
        engine, auth, target, list(SYSTEM_OIDS.values())
    )
    uptime_ticks = snmp_int(values.get(SYSTEM_OIDS["uptime"]))
    return SystemInfo(
        name=text_value(values.get(SYSTEM_OIDS["name"])),
        description=text_value(values.get(SYSTEM_OIDS["description"])),
        uptime_seconds=uptime_ticks // 100 if uptime_ticks is not None else None,
    )


async def poll_interfaces(
    engine: Any, auth: Any, target: Any
) -> dict[int, InterfaceData]:
    tables = {
        name: await _walk(engine, auth, target, oid)
        for name, oid in INTERFACE_COLUMNS.items()
    }

    indexes = set(tables["name"]) | set(tables["description"])
    interfaces: dict[int, InterfaceData] = {}
    for index in indexes:
        speed = snmp_int(tables["speed"].get(index))
        in_octets = tables["in_octets"].get(index)
        out_octets = tables["out_octets"].get(index)
        if in_octets is None:
            in_octets = tables["in_octets_32"].get(index)
        if out_octets is None:
            out_octets = tables["out_octets_32"].get(index)
        name = text_value(tables["name"].get(index)) or text_value(
            tables["description"].get(index)
        )
        if name is None:
            continue
        interfaces[index] = InterfaceData(
            name=name,
            alias=text_value(tables["alias"].get(index)),
            admin=snmp_int(tables["admin"].get(index)),
            oper=snmp_int(tables["oper"].get(index)),
            speed=speed if speed and speed > 0 else None,
            in_octets=snmp_int(in_octets),
            out_octets=snmp_int(out_octets),
            in_errors=snmp_int(tables["in_errors"].get(index)),
            out_errors=snmp_int(tables["out_errors"].get(index)),
            in_discards=snmp_int(tables["in_discards"].get(index)),
            out_discards=snmp_int(tables["out_discards"].get(index)),
            crc_errors=snmp_int(tables["crc_errors"].get(index)),
        )
    return interfaces


async def _safe_walk(
    engine: Any, auth: Any, target: Any, oid: str, *, device_name: str, table: str
) -> dict[int, Any]:
    try:
        return await _walk(engine, auth, target, oid)
    except OSError as exc:
        logger.info(
            "%s data unavailable for %s: %s",
            table,
            device_name,
            type(exc).__name__,
        )
        return {}


async def poll_standard_health(
    engine: Any, auth: Any, target: Any, device_name: str
) -> HealthData:
    """Poll standard HOST-RESOURCES-MIB and ENTITY-SENSOR-MIB health.

    No vendor MIBs are read here.  Vendor-specific health belongs in the
    vendor collector package.
    """
    cpu = await _safe_walk(
        engine,
        auth,
        target,
        HOST_CPU_LOAD,
        device_name=device_name,
        table="HOST-RESOURCES CPU",
    )
    storage = {}
    for name, oid in HOST_STORAGE.items():
        storage[name] = await _safe_walk(
            engine,
            auth,
            target,
            oid,
            device_name=device_name,
            table="HOST-RESOURCES storage",
        )
    sensors = {}
    for name, oid in ENTITY_SENSOR_COLUMNS.items():
        sensors[name] = await _safe_walk(
            engine,
            auth,
            target,
            oid,
            device_name=device_name,
            table="ENTITY-SENSOR",
        )

    cpu_values = [
        parsed for raw in cpu.values() if (parsed := snmp_int(raw)) is not None
    ]
    cpu_percent = sum(cpu_values) / len(cpu_values) if cpu_values else None

    memory_total = 0
    memory_used = 0
    memory_found = False
    for index, raw_type in storage.get("type", {}).items():
        if snmp_int(raw_type) != 2:
            continue
        units = snmp_int(storage.get("allocation_units", {}).get(index))
        size = snmp_int(storage.get("size", {}).get(index))
        used = snmp_int(storage.get("used", {}).get(index))
        if units is None or size is None or used is None or min(units, size, used) < 0:
            continue
        memory_total += units * size
        memory_used += units * used
        memory_found = True

    temperatures: list[float] = []
    voltages: list[float] = []
    fan_speeds: list[float] = []
    for index, raw_type in sensors.get("type", {}).items():
        sensor_type = snmp_int(raw_type)
        value = snmp_number(sensors.get("value", {}).get(index))
        scale = snmp_int(sensors.get("scale", {}).get(index))
        precision = snmp_int(sensors.get("precision", {}).get(index))
        if value is None or scale is None or precision is None:
            continue
        measured = value * 10 ** (scale - 10 - precision)
        if sensor_type == 8:
            temperatures.append(measured)
        elif sensor_type == 4:
            voltages.append(measured)
        elif sensor_type == 10 and measured > 0:
            fan_speeds.append(measured)

    return HealthData(
        cpu_usage_percent=cpu_percent,
        memory_total_bytes=memory_total if memory_found else None,
        memory_used_bytes=memory_used if memory_found else None,
        temperature_celsius=max(temperatures) if temperatures else None,
        voltage_volts=max(voltages) if voltages else None,
        fan_speed_rpm=min(fan_speeds) if fan_speeds else None,
    )


async def poll_lldp_neighbors(
    engine: Any, auth: Any, target: Any
) -> list[NeighborData]:
    """Read the LLDP remote table and normalise adjacencies."""
    tables: dict[str, dict[str, Any]] = {}
    for name, oid in LLDP_REM_COLUMNS.items():
        try:
            tables[name] = await _walk_raw(engine, auth, target, oid)
        except OSError:
            logger.info("LLDP table %s unavailable", name)
            tables[name] = {}

    suffixes = set(tables.get("system_name", {}))
    suffixes.update(tables.get("chassis_id", {}))
    if not suffixes:
        return []

    interface_names = _interface_names(
        await _walk(engine, auth, target, IF_NAME), "if"
    )
    neighbors: dict[tuple[str, str, str], NeighborData] = {}
    for suffix in suffixes:
        parts = suffix.split(".")
        if len(parts) < 3:
            continue
        try:
            local_port = int(parts[-2])
        except ValueError:
            continue
        local_interface = interface_names.get(local_port, f"if{local_port}")
        remote_device = text_value(tables["system_name"].get(suffix))
        remote_interface = decode_identifier(
            tables["port_id"].get(suffix),
            snmp_int(tables["port_subtype"].get(suffix)),
        ) or text_value(tables["port_description"].get(suffix))
        chassis_subtype = snmp_int(tables["chassis_subtype"].get(suffix))
        remote_address = decode_identifier(
            tables["chassis_id"].get(suffix), chassis_subtype
        )
        neighbor = NeighborData(
            protocol="lldp",
            local_interface=local_interface,
            remote_device=remote_device or remote_address,
            remote_interface=remote_interface,
            remote_platform=text_value(tables["system_description"].get(suffix)),
            remote_address=remote_address if chassis_subtype == 4 else None,
            capabilities=capability_names(
                tables["capabilities"].get(suffix)
            ),
        )
        key = (
            neighbor.local_interface,
            neighbor.remote_device or "",
            neighbor.remote_interface or "",
        )
        neighbors[key] = neighbor
    return sorted(
        neighbors.values(),
        key=lambda item: (
            item.local_interface,
            item.remote_device or "",
            item.remote_interface or "",
        ),
    )


class GenericSNMPCollector(BaseCollector):
    """Standard SNMP collector used by every SNMP-capable device."""

    async def collect_system(self, device: Device) -> SystemInfo:
        engine, auth, target = await _open_target(device)
        try:
            return await poll_system(engine, auth, target)
        finally:
            engine.close_dispatcher()

    async def collect_interfaces(self, device: Device) -> dict[int, InterfaceData]:
        engine, auth, target = await _open_target(device)
        try:
            return await poll_interfaces(engine, auth, target)
        finally:
            engine.close_dispatcher()

    async def collect_health(self, device: Device) -> HealthData:
        engine, auth, target = await _open_target(device)
        try:
            return await poll_standard_health(
                engine, auth, target, device.name
            )
        finally:
            engine.close_dispatcher()

    async def discover_neighbors(self, device: Device) -> list[NeighborData]:
        engine, auth, target = await _open_target(device)
        try:
            return await poll_lldp_neighbors(engine, auth, target)
        finally:
            engine.close_dispatcher()

    async def collect(self, device: Device) -> CollectionResult:
        """Poll all standard tables over one SNMP session."""
        engine, auth, target = await _open_target(device)
        try:
            system = await poll_system(engine, auth, target)
            interfaces = await poll_interfaces(engine, auth, target)
            health = await poll_standard_health(
                engine, auth, target, device.name
            )
            neighbors = await poll_lldp_neighbors(engine, auth, target)
        finally:
            engine.close_dispatcher()
        return CollectionResult(
            interfaces={
                index: interface.model_dump()
                for index, interface in interfaces.items()
            },
            system=system,
            health=health,
            neighbors=neighbors,
        )


# Backwards-compatible private aliases used by existing integrations/tests.
_open_target = open_target
_get = snmp_get
_walk = snmp_walk
_walk_raw = snmp_walk_raw
_int = snmp_int
_number = snmp_number
safe_walk = _safe_walk
