"""Alert history and maintenance-window state."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

ALERT_STATUS_FIRING = "firing"
ALERT_STATUS_RESOLVED = "resolved"

MAINTENANCE_SCOPE_DEVICE = "device"
MAINTENANCE_SCOPE_GROUP = "group"
MAINTENANCE_SCOPE_SITE = "site"


class AlertEvent(TimestampMixin, Base):
    __tablename__ = "alert_events"
    __table_args__ = (
        UniqueConstraint(
            "fingerprint",
            "starts_at",
            name="uq_alert_events_fingerprint_starts_at",
        ),
        CheckConstraint("status IN ('firing', 'resolved')", name="valid_alert_status"),
        CheckConstraint(
            "ends_at IS NULL OR ends_at >= starts_at", name="valid_alert_window"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        default=uuid4,
        server_default=text("gen_random_uuid()"),
        unique=True,
        nullable=False,
    )
    fingerprint: Mapped[str] = mapped_column(String(128), index=True)
    alertname: Mapped[str] = mapped_column(String(120), index=True)
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), index=True
    )
    device_name: Mapped[str | None] = mapped_column(String(120))
    site: Mapped[str | None] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    status: Mapped[str] = mapped_column(
        String(16), default=ALERT_STATUS_FIRING, index=True
    )
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    labels: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    annotations: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    raw: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(String(120))
    suppressed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), index=True
    )
    last_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class MaintenanceWindow(TimestampMixin, Base):
    __tablename__ = "maintenance_windows"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('device', 'group', 'site')",
            name="valid_maintenance_scope",
        ),
        CheckConstraint(
            "(scope_type = 'device' AND device_id IS NOT NULL AND "
            "group_id IS NULL AND site_id IS NULL) OR "
            "(scope_type = 'group' AND group_id IS NOT NULL AND "
            "device_id IS NULL AND site_id IS NULL) OR "
            "(scope_type = 'site' AND site_id IS NOT NULL AND "
            "device_id IS NULL AND group_id IS NULL)",
            name="valid_maintenance_target",
        ),
        CheckConstraint("ends_at > starts_at", name="valid_maintenance_window"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        default=uuid4,
        server_default=text("gen_random_uuid()"),
        unique=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    scope_type: Mapped[str] = mapped_column(String(16))
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("device_groups.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    suppress_notifications: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    silence_ids: Mapped[str | None] = mapped_column(String(512))
    created_by: Mapped[str | None] = mapped_column(String(120))
