"""Typed contracts shared by all device collectors.

Every collector implements the same four operations:

``collect_system``, ``collect_interfaces``, ``collect_health`` and
``discover_neighbors``.  ``collect`` is a convenience batch entry point that
collectors may override when their transport can reuse a single session.

The contracts intentionally expose no vendor-specific fields.  Vendor data
belongs in the collector package and is normalised into these models before it
crosses the collector boundary.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.models import Device


class SystemInfo(BaseModel):
    name: str | None = None
    description: str | None = None
    uptime_seconds: int | None = None


class InterfaceData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    alias: str | None = None
    admin: int | None = None
    oper: int | None = None
    speed: int | None = None
    in_octets: int | None = None
    out_octets: int | None = None
    in_errors: int | None = None
    out_errors: int | None = None
    in_discards: int | None = None
    out_discards: int | None = None
    crc_errors: int | None = None


class HealthData(BaseModel):
    cpu_usage_percent: float | None = None
    memory_total_bytes: int | None = None
    memory_used_bytes: int | None = None
    disk_total_bytes: int | None = None
    disk_used_bytes: int | None = None
    temperature_celsius: float | None = None
    voltage_volts: float | None = None
    fan_speed_rpm: float | None = None
    fans_ok: bool | None = None
    power_supplies_ok: bool | None = None


class NeighborData(BaseModel):
    """One discovered adjacency.

    Neighbour identifiers are intentionally kept out of Prometheus labels;
    the worker persists them in PostgreSQL instead.
    """

    model_config = ConfigDict(extra="forbid")

    protocol: Literal["cdp", "lldp", "routeros"]
    local_interface: str
    remote_device: str | None = None
    remote_interface: str | None = None
    remote_platform: str | None = None
    remote_address: str | None = None
    capabilities: str | None = None


@dataclass
class CollectionResult:
    interfaces: dict[int, dict[str, Any]] = field(default_factory=dict)
    system: SystemInfo | None = None
    health: HealthData | None = None
    neighbors: list[NeighborData] = field(default_factory=list)
    snapshots: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


class BaseCollector(ABC):
    """Common async collector API.

    Implementations should keep one network session per ``collect`` call when
    possible.  The single-operation methods exist for targeted tests and for
    integrations that need only one slice of telemetry.
    """

    @abstractmethod
    async def collect_system(self, device: Device) -> SystemInfo:
        ...

    @abstractmethod
    async def collect_interfaces(self, device: Device) -> dict[int, InterfaceData]:
        ...

    @abstractmethod
    async def collect_health(self, device: Device) -> HealthData:
        ...

    @abstractmethod
    async def discover_neighbors(self, device: Device) -> list[NeighborData]:
        ...

    async def collect(self, device: Device) -> CollectionResult:
        system = await self.collect_system(device)
        interfaces = await self.collect_interfaces(device)
        health = await self.collect_health(device)
        neighbors = await self.discover_neighbors(device)
        return CollectionResult(
            interfaces={
                index: interface.model_dump()
                for index, interface in interfaces.items()
            },
            system=system,
            health=health,
            neighbors=neighbors,
        )


Collector = BaseCollector
