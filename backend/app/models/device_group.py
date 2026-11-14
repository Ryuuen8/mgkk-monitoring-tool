from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.device import Device

# Many-to-many join table. Plain Table (no ORM class) because it carries no
# extra data; use an association object instead if you later need e.g. "added_by".
device_group_members = Table(
    "device_group_members",
    Base.metadata,
    Column(
        "device_id",
        BigInteger,
        ForeignKey("devices.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "group_id",
        BigInteger,
        ForeignKey("device_groups.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    # The composite PK covers lookups by device_id; this covers group_id.
    Index("ix_device_group_members_group_id", "group_id"),
)


class DeviceGroup(TimestampMixin, Base):
    __tablename__ = "device_groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Stable public identity used by the versioned API.
    public_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        default=uuid4,
        server_default=text("gen_random_uuid()"),
        unique=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)

    devices: Mapped[list["Device"]] = relationship(
        secondary=device_group_members,
        back_populates="groups",
        passive_deletes=True,
    )
