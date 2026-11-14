"""Critical syslog events retained in PostgreSQL."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SyslogEvent(TimestampMixin, Base):
    __tablename__ = "syslog_events"
    __table_args__ = (
        Index("ix_syslog_events_device_occurred", "device_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        default=uuid4,
        server_default=text("gen_random_uuid()"),
        unique=True,
        nullable=False,
    )
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), index=True
    )
    source_ip: Mapped[str] = mapped_column(INET, index=True)
    facility: Mapped[int] = mapped_column(Integer, default=1)
    severity: Mapped[int] = mapped_column(Integer, default=6, index=True)
    hostname: Mapped[str | None] = mapped_column(String(255))
    app_name: Mapped[str | None] = mapped_column(String(120))
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    message: Mapped[str] = mapped_column(Text)
    raw: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
