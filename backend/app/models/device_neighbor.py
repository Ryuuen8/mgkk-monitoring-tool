"""Discovered topology adjacencies.

Only aggregate counts are exported to Prometheus.  Neighbour names, addresses,
platforms, and port identifiers are stored here instead of becoming labels.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DeviceNeighbor(Base):
    __tablename__ = "device_neighbors"
    __table_args__ = (
        UniqueConstraint(
            "device_id",
            "protocol",
            "local_interface",
            "remote_device",
            "remote_interface",
            name="uq_device_neighbors_identity",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    protocol: Mapped[str] = mapped_column(String(16))
    local_interface: Mapped[str] = mapped_column(String(255))
    remote_device: Mapped[str | None] = mapped_column(String(255))
    remote_interface: Mapped[str | None] = mapped_column(String(255))
    remote_platform: Mapped[str | None] = mapped_column(String(255))
    remote_address: Mapped[str | None] = mapped_column(String(64))
    capabilities: Mapped[str | None] = mapped_column(String(255))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
