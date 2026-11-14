"""Cisco IOS, IOS-XE, and NX-OS collector.

SNMP is the primary transport and reuses the shared ``generic_snmp`` system,
IF-MIB, standard health, and LLDP code.  Only the Cisco Enterprise MIBs in
:mod:`app.collectors.cisco.mibs` are implemented here.  IOS-XE RESTCONF is an
optional alternative check type.
"""

import logging
from typing import Any

from app.collectors.base import (
    BaseCollector,
    CollectionResult,
    HealthData,
    InterfaceData,
    NeighborData,
    SystemInfo,
)
from app.collectors.cisco import mibs
from app.collectors.cisco.restconf import collect_restconf
from app.collectors.generic_snmp import collector as generic
from app.models import Device, DeviceCheckType

logger = logging.getLogger(__name__)

_MAX_TEXT = 255


def _cdp_capabilities(value: Any) -> str | None:
    bits = generic.snmp_int(value)
    if bits is None:
        return None
    names = [
        name
        for bit, name in enumerate(mibs.CDP_CAPABILITIES)
        if bits & (1 << bit)
    ]
    return ",".join(names) or None


def _merge_neighbors(groups: list[NeighborData]) -> list[NeighborData]:
    merged: dict[tuple[str, str, str, str], NeighborData] = {}
    for neighbor in groups:
        key = (
            neighbor.protocol,
            neighbor.local_interface,
            neighbor.remote_device or "",
            neighbor.remote_interface or "",
        )
        merged[key] = neighbor
    return sorted(
        merged.values(),
        key=lambda item: (
            item.local_interface,
            item.protocol,
            item.remote_device or "",
        ),
    )


def _state_counts(states: dict[int, Any]) -> tuple[int, int] | None:
    active = [
        state
        for raw in states.values()
        if (state := generic.snmp_int(raw)) is not None
        and state != mibs.ENVMON_STATE_NOT_PRESENT
    ]
    if not active:
        return None
    failed = sum(state != mibs.ENVMON_STATE_NORMAL for state in active)
    return len(active), failed


def _state_ok(states: dict[int, Any]) -> bool | None:
    counts = _state_counts(states)
    if counts is None:
        return None
    return counts[1] == 0


async def _first_walk(
    engine: Any, auth: Any, target: Any, oids: list[str], *, device_name: str
) -> dict[int, Any]:
    for oid in oids:
        table = await generic.safe_walk(
            engine,
            auth,
            target,
            oid,
            device_name=device_name,
            table="Cisco MIB",
        )
        if table:
            return table
    return {}


async def poll_cisco_health(
    engine: Any, auth: Any, target: Any, fallback: HealthData, device_name: str
) -> HealthData:
    """Merge CISCO-PROCESS-MIB, CISCO-MEMORY-POOL-MIB, and ENVMON data."""
    cpu_table = await _first_walk(
        engine,
        auth,
        target,
        [
            mibs.CPU_COLUMNS["five_minutes"],
            mibs.CPU_COLUMNS["one_minute"],
            mibs.CPU_COLUMNS["five_seconds"],
        ],
        device_name=device_name,
    )
    cpu_values = [
        value
        for raw in cpu_table.values()
        if (value := generic.snmp_int(raw)) is not None
    ]
    cpu_percent = sum(cpu_values) / len(cpu_values) if cpu_values else None

    memory_used_table = await generic.safe_walk(
        engine,
        auth,
        target,
        mibs.MEMORY_COLUMNS["used"],
        device_name=device_name,
        table="CISCO-MEMORY-POOL used",
    )
    memory_free_table = await generic.safe_walk(
        engine,
        auth,
        target,
        mibs.MEMORY_COLUMNS["free"],
        device_name=device_name,
        table="CISCO-MEMORY-POOL free",
    )
    memory_used = sum(
        value
        for raw in memory_used_table.values()
        if (value := generic.snmp_int(raw)) is not None
    )
    memory_free = sum(
        value
        for raw in memory_free_table.values()
        if (value := generic.snmp_int(raw)) is not None
    )
    memory_total = (
        memory_used + memory_free
        if memory_used_table or memory_free_table
        else None
    )

    temperature_table = await _first_walk(
        engine,
        auth,
        target,
        [
            mibs.ENVMON_TEMPERATURE_VALUE_REV1,
            mibs.ENVMON_TEMPERATURE_VALUE,
        ],
        device_name=device_name,
    )
    temperature_values = [
        measured
        for raw in temperature_table.values()
        if (measured := generic.snmp_number(raw)) is not None and measured > 0
    ]

    voltage_table = await generic.safe_walk(
        engine,
        auth,
        target,
        mibs.ENVMON_VOLTAGE_VALUE,
        device_name=device_name,
        table="CISCO-ENVMON voltage",
    )
    voltage_values = [
        measured / 1000
        for raw in voltage_table.values()
        if (measured := generic.snmp_number(raw)) is not None and measured > 0
    ]

    fan_states = await generic.safe_walk(
        engine,
        auth,
        target,
        mibs.ENVMON_FAN_STATE,
        device_name=device_name,
        table="CISCO-ENVMON fans",
    )
    supply_states = await generic.safe_walk(
        engine,
        auth,
        target,
        mibs.ENVMON_SUPPLY_STATE,
        device_name=device_name,
        table="CISCO-ENVMON power supplies",
    )

    updates: dict[str, Any] = {}
    if cpu_percent is not None:
        updates["cpu_usage_percent"] = cpu_percent
    if memory_total is not None:
        updates["memory_total_bytes"] = memory_total
        updates["memory_used_bytes"] = memory_used
    if temperature_values:
        updates["temperature_celsius"] = max(temperature_values)
    if voltage_values:
        updates["voltage_volts"] = max(voltage_values)
    fans_ok = _state_ok(fan_states)
    if fans_ok is not None:
        updates["fans_ok"] = fans_ok
    supply_counts = _state_counts(supply_states)
    if supply_counts is not None:
        total, failed = supply_counts
        updates["power_supplies_total"] = total
        updates["power_supplies_failed"] = failed
        updates["power_supplies_ok"] = failed == 0
    return fallback.model_copy(update=updates) if updates else fallback


async def poll_cdp_neighbors(
    engine: Any, auth: Any, target: Any
) -> list[NeighborData]:
    tables: dict[str, dict[str, Any]] = {}
    for name, oid in mibs.CDP_COLUMNS.items():
        try:
            tables[name] = await generic.snmp_walk_raw(engine, auth, target, oid)
        except OSError:
            logger.info("CDP table %s unavailable", name)
            tables[name] = {}

    suffixes: set[str] = set()
    suffixes.update(tables.get("device_id", {}))
    suffixes.update(tables.get("device_port", {}))
    if not suffixes:
        return []

    interface_names = {
        index: generic.text_value(value) or f"if{index}"
        for index, value in (
            await generic.snmp_walk(engine, auth, target, generic.IF_NAME)
        ).items()
    }
    neighbors: list[NeighborData] = []
    for suffix in suffixes:
        parts = suffix.split(".")
        if len(parts) < 2:
            continue
        try:
            local_index = int(parts[0])
        except ValueError:
            continue
        address = generic.decode_address(tables["address"].get(suffix))
        device_id = generic.text_value(tables["device_id"].get(suffix))
        port_id = generic.text_value(tables["device_port"].get(suffix))
        platform = generic.text_value(tables["platform"].get(suffix))
        neighbors.append(
            NeighborData(
                protocol="cdp",
                local_interface=interface_names.get(local_index, f"if{local_index}"),
                remote_device=(device_id or address or "")[:_MAX_TEXT] or None,
                remote_interface=(
                    port_id[:_MAX_TEXT] if port_id else None
                ),
                remote_platform=(
                    platform[:_MAX_TEXT] if platform else None
                ),
                remote_address=address,
                capabilities=_cdp_capabilities(
                    tables["capabilities"].get(suffix)
                ),
            )
        )
    return _merge_neighbors(neighbors)


async def poll_stack_members(
    engine: Any, auth: Any, target: Any, device_name: str
) -> list[dict[str, Any]]:
    """Read CISCO-STACKWISE-MIB into a PostgreSQL snapshot."""
    tables = {
        name: await generic.safe_walk(
            engine,
            auth,
            target,
            oid,
            device_name=device_name,
            table=f"CISCO-STACKWISE {name}",
        )
        for name, oid in mibs.STACKWISE_COLUMNS.items()
    }
    indexes: set[int] = set()
    for table in tables.values():
        indexes.update(table)
    members: list[dict[str, Any]] = []
    for index in sorted(indexes):
        role = generic.snmp_int(tables["role"].get(index))
        state = generic.snmp_int(tables["state"].get(index))
        members.append(
            {
                "member": index,
                "role": mibs.STACKWISE_ROLE_NAMES.get(role or 0),
                "state": mibs.STACKWISE_STATE_NAMES.get(state or 0),
                "software_priority": generic.snmp_int(
                    tables["software_priority"].get(index)
                ),
                "hardware_priority": generic.snmp_int(
                    tables["hardware_priority"].get(index)
                ),
                "mac_address": generic.text_value(
                    tables["mac_address"].get(index)
                ),
                "software_image": generic.text_value(
                    tables["software_image"].get(index)
                ),
            }
        )
    return members


class CiscoCollector(BaseCollector):
    """Unified Cisco collector for IOS, IOS-XE, and NX-OS."""

    async def collect(self, device: Device) -> CollectionResult:
        if device.check_type is DeviceCheckType.RESTCONF:
            return await collect_restconf(device)

        engine, auth, target = await generic.open_target(device)
        try:
            system = await generic.poll_system(engine, auth, target)
            interfaces = await generic.poll_interfaces(engine, auth, target)
            health = await generic.poll_standard_health(
                engine, auth, target, device.name
            )
            health = await poll_cisco_health(
                engine, auth, target, health, device.name
            )
            neighbors = _merge_neighbors(
                await poll_cdp_neighbors(engine, auth, target)
                + await generic.poll_lldp_neighbors(engine, auth, target)
            )
            stack_members = await poll_stack_members(
                engine, auth, target, device.name
            )
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
            snapshots={"stack_members": stack_members} if stack_members else {},
        )

    async def collect_system(self, device: Device) -> SystemInfo:
        if device.check_type is DeviceCheckType.RESTCONF:
            result = await collect_restconf(device)
            if result.system is None:
                raise RuntimeError("RESTCONF returned no system data")
            return result.system
        engine, auth, target = await generic.open_target(device)
        try:
            return await generic.poll_system(engine, auth, target)
        finally:
            engine.close_dispatcher()

    async def collect_interfaces(self, device: Device) -> dict[int, InterfaceData]:
        if device.check_type is DeviceCheckType.RESTCONF:
            result = await collect_restconf(device)
            return {
                index: InterfaceData.model_validate(row)
                for index, row in result.interfaces.items()
            }
        engine, auth, target = await generic.open_target(device)
        try:
            return await generic.poll_interfaces(engine, auth, target)
        finally:
            engine.close_dispatcher()

    async def collect_health(self, device: Device) -> HealthData:
        if device.check_type is DeviceCheckType.RESTCONF:
            result = await collect_restconf(device)
            if result.health is None:
                raise RuntimeError("RESTCONF returned no health data")
            return result.health
        engine, auth, target = await generic.open_target(device)
        try:
            health = await generic.poll_standard_health(
                engine, auth, target, device.name
            )
            return await poll_cisco_health(
                engine, auth, target, health, device.name
            )
        finally:
            engine.close_dispatcher()

    async def discover_neighbors(self, device: Device) -> list[NeighborData]:
        if device.check_type is DeviceCheckType.RESTCONF:
            result = await collect_restconf(device)
            return result.neighbors
        engine, auth, target = await generic.open_target(device)
        try:
            return _merge_neighbors(
                await poll_cdp_neighbors(engine, auth, target)
                + await generic.poll_lldp_neighbors(engine, auth, target)
            )
        finally:
            engine.close_dispatcher()
