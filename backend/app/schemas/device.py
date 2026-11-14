import re
from datetime import datetime
from typing import Any

from pydantic import (
    BaseModel,
    Field,
    IPvAnyAddress,
    field_serializer,
    field_validator,
)

from app.models.enums import CollectorType, DeviceCheckType, DeviceType
from app.schemas.common import ORMModel, Timestamps
from app.schemas.credentials import CredentialProfileRef
from app.schemas.device_group import DeviceGroupRef
from app.schemas.site import SiteRef

_MAC_RE = re.compile(r"^[0-9a-f]{12}$")


def normalize_mac(value: str | None) -> str | None:
    """Accept aa:bb:cc:dd:ee:ff, aa-bb-..., aabb.ccdd.eeff, or bare hex.

    Returns lowercase colon-separated form, which PostgreSQL's MACADDR accepts.
    """
    if value is None:
        return None
    digits = re.sub(r"[:\-.\s]", "", value).lower()
    if not _MAC_RE.match(digits):
        raise ValueError("invalid MAC address")
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


class DeviceBase(BaseModel):
    site_id: int
    name: str = Field(min_length=1, max_length=120)
    hostname: str | None = Field(default=None, max_length=255)
    mgmt_ip: IPvAnyAddress
    mac: str | None = None
    device_type: DeviceType = DeviceType.OTHER
    check_type: DeviceCheckType = DeviceCheckType.PING_ONLY
    collector: CollectorType = CollectorType.GENERIC
    credential_profile_id: int | None = None
    vendor: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=120)
    os_version: str | None = Field(default=None, max_length=64)
    serial_number: str | None = Field(default=None, max_length=120)
    parent_device_id: int | None = None
    poll_interval_seconds: int = Field(default=60, ge=10, le=3600)
    is_active: bool = True
    tags: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None

    @field_validator("mac")
    @classmethod
    def _check_mac(cls, v: str | None) -> str | None:
        return normalize_mac(v)

    @field_validator("collector", mode="before")
    @classmethod
    def _legacy_generic_collector(cls, value: object) -> object:
        return "generic_snmp" if value == "generic" else value

    @field_validator("vendor")
    @classmethod
    def _lower_vendor(cls, v: str | None) -> str | None:
        # Vendor selects the collector module, so keep it lowercase ("mikrotik").
        return v.strip().lower() if v else v

    # SQLAlchemy's INET column expects text, not ipaddress objects.
    @field_serializer("mgmt_ip")
    def _ser_ip(self, v: IPvAnyAddress) -> str:
        return str(v)


class DeviceCreate(DeviceBase):
    group_ids: list[int] = Field(default_factory=list)


class DeviceUpdate(BaseModel):
    """All fields optional; apply with model_dump(exclude_unset=True)."""

    site_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    hostname: str | None = Field(default=None, max_length=255)
    mgmt_ip: IPvAnyAddress | None = None
    mac: str | None = None
    device_type: DeviceType | None = None
    check_type: DeviceCheckType | None = None
    collector: CollectorType | None = None
    credential_profile_id: int | None = None
    vendor: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=120)
    os_version: str | None = Field(default=None, max_length=64)
    serial_number: str | None = Field(default=None, max_length=120)
    parent_device_id: int | None = None
    poll_interval_seconds: int | None = Field(default=None, ge=10, le=3600)
    is_active: bool | None = None
    tags: dict[str, Any] | None = None
    notes: str | None = None
    group_ids: list[int] | None = None

    @field_validator("mac")
    @classmethod
    def _check_mac(cls, v: str | None) -> str | None:
        return normalize_mac(v)

    @field_validator("collector", mode="before")
    @classmethod
    def _legacy_generic_collector(cls, value: object) -> object:
        return "generic_snmp" if value == "generic" else value

    @field_validator("vendor")
    @classmethod
    def _lower_vendor(cls, v: str | None) -> str | None:
        return v.strip().lower() if v else v

    @field_serializer("mgmt_ip")
    def _ser_ip(self, v: IPvAnyAddress | None) -> str | None:
        return str(v) if v is not None else None


class DeviceRead(DeviceBase, Timestamps):
    """Flat response: safe to build without loading any relationships."""

    id: int
    last_seen_at: datetime | None = None
    snmp_system_name: str | None = None
    snmp_system_description: str | None = None
    uptime_seconds: int | None = None
    cpu_usage_percent: float | None = None
    memory_total_bytes: int | None = None
    memory_used_bytes: int | None = None
    disk_total_bytes: int | None = None
    disk_used_bytes: int | None = None
    temperature_celsius: float | None = None
    voltage_volts: float | None = None
    dhcp_lease_count: int | None = None
    arp_entry_count: int | None = None


class DeviceDetail(DeviceRead):
    """Response with relationships. Load them first with selectinload()."""

    site: SiteRef
    groups: list[DeviceGroupRef] = Field(default_factory=list)
    parent: "DeviceRef | None" = None
    credential_profile: CredentialProfileRef | None = None


class DeviceRef(ORMModel):
    id: int
    name: str
    mgmt_ip: IPvAnyAddress

    @field_serializer("mgmt_ip")
    def _ser_ip(self, v: IPvAnyAddress) -> str:
        return str(v)


DeviceDetail.model_rebuild()
