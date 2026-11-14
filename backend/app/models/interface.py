from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.device import Device


class NetworkInterface(TimestampMixin, Base):
    __tablename__ = "network_interfaces"
    __table_args__ = (
        UniqueConstraint("device_id", "if_index", name="uq_interface_device_index"),
        CheckConstraint(
            "link_speed_override_mbps IS NULL OR link_speed_override_mbps > 0",
            name="valid_link_speed_override",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    if_index: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    alias: Mapped[str | None] = mapped_column(String(255))
    admin_status: Mapped[int | None] = mapped_column(Integer)
    oper_status: Mapped[int | None] = mapped_column(Integer)
    link_speed_mbps: Mapped[int | None] = mapped_column(BigInteger)
    link_speed_override_mbps: Mapped[int | None] = mapped_column(BigInteger)
    last_in_octets: Mapped[Decimal | None] = mapped_column(Numeric(20, 0))
    last_out_octets: Mapped[Decimal | None] = mapped_column(Numeric(20, 0))
    last_in_errors: Mapped[Decimal | None] = mapped_column(Numeric(20, 0))
    last_out_errors: Mapped[Decimal | None] = mapped_column(Numeric(20, 0))
    last_crc_errors: Mapped[Decimal | None] = mapped_column(Numeric(20, 0))
    last_in_discards: Mapped[Decimal | None] = mapped_column(Numeric(20, 0))
    last_out_discards: Mapped[Decimal | None] = mapped_column(Numeric(20, 0))
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    device: Mapped["Device"] = relationship(back_populates="interfaces")
