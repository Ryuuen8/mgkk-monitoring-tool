from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, MACADDR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.device_group import device_group_members
from app.models.enums import CollectorType, DeviceCheckType, DeviceType

if TYPE_CHECKING:
    from app.models.credentials import CredentialProfile
    from app.models.device_group import DeviceGroup
    from app.models.interface import NetworkInterface
    from app.models.site import Site


class Device(TimestampMixin, Base):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint("parent_device_id <> id", name="no_self_parent"),
        CheckConstraint("poll_interval_seconds >= 10", name="min_poll_interval"),
        CheckConstraint(
            "(check_type = 'ping_only' AND credential_profile_id IS NULL) OR "
            "(check_type IN ('snmp', 'routeros_api') AND "
            "credential_profile_id IS NOT NULL)",
            name="check_credentials",
        ),
    )

    # Identity is the row id, never the IP: DHCP and re-addressing happen.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="RESTRICT"), index=True
    )
    # Used as the `device` Prometheus label.
    name: Mapped[str] = mapped_column(String(120), unique=True)
    hostname: Mapped[str | None] = mapped_column(String(255))

    # Address the pollers use. Indexed but not unique.
    mgmt_ip: Mapped[str] = mapped_column(INET, index=True)
    mac: Mapped[str | None] = mapped_column(MACADDR, index=True)

    # Stored as a VARCHAR + CHECK rather than a native PostgreSQL enum, so adding
    # a new device type later is a simple migration (no ALTER TYPE).
    device_type: Mapped[DeviceType] = mapped_column(
        Enum(
            DeviceType,
            name="device_type",
            native_enum=False,
            length=20,
            create_constraint=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        default=DeviceType.OTHER,
        server_default=DeviceType.OTHER.value,
    )
    check_type: Mapped[DeviceCheckType] = mapped_column(
        Enum(
            DeviceCheckType,
            name="device_check_type",
            native_enum=False,
            length=20,
            create_constraint=True,
            values_callable=lambda e: [member.value for member in e],
        ),
        default=DeviceCheckType.PING_ONLY,
        server_default=DeviceCheckType.PING_ONLY.value,
    )
    collector: Mapped[CollectorType] = mapped_column(
        Enum(
            CollectorType,
            name="collector_type",
            native_enum=False,
            length=20,
            create_constraint=True,
            values_callable=lambda e: [member.value for member in e],
        ),
        default=CollectorType.GENERIC,
        server_default=CollectorType.GENERIC.value,
    )
    vendor: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(120))
    os_version: Mapped[str | None] = mapped_column(String(64))
    serial_number: Mapped[str | None] = mapped_column(String(120))

    # Upstream device, used for alert inhibition (Phase 3) and topology hints.
    parent_device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), index=True
    )

    poll_interval_seconds: Mapped[int] = mapped_column(
        Integer, default=60, server_default=text("60")
    )
    credential_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("credential_profiles.id", ondelete="RESTRICT"), index=True
    )

    # Soft delete / pause switch. Alert history keeps referencing the row.
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), index=True
    )
    # Cached convenience value; Prometheus remains the source of truth.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snmp_system_name: Mapped[str | None] = mapped_column(String(255))
    snmp_system_description: Mapped[str | None] = mapped_column(Text)
    uptime_seconds: Mapped[int | None] = mapped_column(BigInteger)
    cpu_usage_percent: Mapped[float | None] = mapped_column(Float)
    memory_total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    memory_used_bytes: Mapped[int | None] = mapped_column(BigInteger)
    disk_total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    disk_used_bytes: Mapped[int | None] = mapped_column(BigInteger)
    temperature_celsius: Mapped[float | None] = mapped_column(Float)
    voltage_volts: Mapped[float | None] = mapped_column(Float)
    dhcp_lease_count: Mapped[int | None] = mapped_column(Integer)
    arp_entry_count: Mapped[int | None] = mapped_column(Integer)

    # Free-form extras. Never promote these to Prometheus labels.
    tags: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    notes: Mapped[str | None] = mapped_column(Text)

    site: Mapped["Site"] = relationship(back_populates="devices")
    groups: Mapped[list["DeviceGroup"]] = relationship(
        secondary=device_group_members,
        back_populates="devices",
        passive_deletes=True,
    )
    parent: Mapped["Device | None"] = relationship(
        remote_side="Device.id", back_populates="children"
    )
    children: Mapped[list["Device"]] = relationship(back_populates="parent")
    credential_profile: Mapped["CredentialProfile | None"] = relationship(
        back_populates="devices"
    )
    interfaces: Mapped[list["NetworkInterface"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )
