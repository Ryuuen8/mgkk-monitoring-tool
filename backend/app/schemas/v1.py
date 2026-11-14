from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    IPvAnyAddress,
    field_serializer,
    field_validator,
)

from app.models.enums import DeviceCheckType, DeviceType, OsFamily
from app.schemas.device import normalize_mac
from app.schemas.metrics import MetricPoint

CollectorV1 = Literal["generic_snmp", "mikrotik", "cisco"]


class SiteV1Read(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(validation_alias="public_id")
    code: str
    name: str
    address: str | None
    timezone: str
    notes: str | None
    created_at: datetime
    updated_at: datetime


class DeviceGroupV1Read(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(validation_alias="public_id")
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class DeviceV1Create(BaseModel):
    site_id: UUID
    name: str = Field(min_length=1, max_length=120)
    ip_address: IPvAnyAddress
    mac_address: str | None = None
    collector: CollectorV1 = "generic_snmp"
    device_type: DeviceType = DeviceType.OTHER
    check_type: DeviceCheckType = DeviceCheckType.PING_ONLY
    credential_profile_id: int | None = None
    vendor: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=120)
    os_family: OsFamily | None = None
    os_version: str | None = Field(default=None, max_length=64)
    parent_device_id: UUID | None = None
    active: bool = True

    @field_validator("mac_address")
    @classmethod
    def validate_mac(cls, value: str | None) -> str | None:
        return normalize_mac(value)

    @field_serializer("ip_address")
    def serialize_ip(self, value: IPvAnyAddress) -> str:
        return str(value)


class DeviceV1Update(BaseModel):
    site_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    ip_address: IPvAnyAddress | None = None
    mac_address: str | None = None
    collector: CollectorV1 | None = None
    device_type: DeviceType | None = None
    check_type: DeviceCheckType | None = None
    credential_profile_id: int | None = None
    vendor: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=120)
    os_family: OsFamily | None = None
    os_version: str | None = Field(default=None, max_length=64)
    parent_device_id: UUID | None = None
    active: bool | None = None

    @field_validator("mac_address")
    @classmethod
    def validate_mac(cls, value: str | None) -> str | None:
        return normalize_mac(value)

    @field_serializer("ip_address")
    def serialize_ip(self, value: IPvAnyAddress | None) -> str | None:
        return str(value) if value is not None else None


class DeviceV1Read(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    site_id: UUID
    name: str
    ip_address: str
    mac_address: str | None
    collector: CollectorV1
    device_type: DeviceType
    check_type: DeviceCheckType
    credential_profile_id: int | None
    vendor: str | None
    model: str | None
    os_family: OsFamily | None
    os_version: str | None
    parent_device_id: UUID | None
    active: bool
    cpu_usage_percent: float | None
    memory_total_bytes: int | None
    memory_used_bytes: int | None
    disk_total_bytes: int | None
    disk_used_bytes: int | None
    temperature_celsius: float | None
    voltage_volts: float | None
    fan_speed_rpm: float | None
    fans_ok: bool | None
    power_supplies_ok: bool | None
    power_supplies_total: int | None
    power_supplies_failed: int | None
    uptime_seconds: int | None
    dhcp_lease_count: int | None
    arp_entry_count: int | None
    created_at: datetime
    updated_at: datetime


class DeviceMetricSeries(BaseModel):
    device_id: UUID
    latency: list[MetricPoint]
    packet_loss_percent: list[MetricPoint]


class DeviceV1Status(BaseModel):
    device_id: UUID
    name: str
    up: bool | None
    latency_ms: float | None
    packet_loss_percent: float | None
    last_seen_at: datetime | None


class ErrorResponse(BaseModel):
    detail: str


class NeighborV1Read(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    protocol: str
    local_interface: str
    remote_device: str | None
    remote_interface: str | None
    remote_platform: str | None
    remote_address: str | None
    capabilities: str | None
    first_seen_at: datetime
    last_seen_at: datetime
