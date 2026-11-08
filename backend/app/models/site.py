from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.device import Device


class Site(TimestampMixin, Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Short, stable identifier; used as the `site` Prometheus label.
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(
        String(64), default="UTC", server_default="UTC"
    )
    notes: Mapped[str | None] = mapped_column(Text)

    # passive_deletes: let the database enforce ON DELETE RESTRICT instead of
    # the ORM trying to null out device.site_id.
    devices: Mapped[list["Device"]] = relationship(
        back_populates="site", passive_deletes=True
    )
