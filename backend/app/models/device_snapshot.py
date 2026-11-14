"""Latest operational snapshots for any collector.

Snapshots are dynamic tables that would explode Prometheus cardinality (DHCP
leases, ARP entries, wireless clients, stack members).  They live in
PostgreSQL and are never used as metric labels.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SNAPSHOT_TYPES = (
    "dhcp_leases",
    "arp_entries",
    "wireless_clients",
    "stack_members",
)


class DeviceSnapshot(Base):
    __tablename__ = "device_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "device_id", "snapshot_type", name="uq_device_snapshots_device_type"
        ),
        CheckConstraint(
            "snapshot_type IN ("
            + ", ".join(f"'{value}'" for value in SNAPSHOT_TYPES)
            + ")",
            name="valid_snapshot_type",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    snapshot_type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
