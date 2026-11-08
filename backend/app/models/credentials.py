import enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Enum,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.device import Device


class CredentialType(str, enum.Enum):
    SNMP_V2C = "snmp_v2c"
    ROUTEROS_API = "routeros_api"


class CredentialProfile(TimestampMixin, Base):
    __tablename__ = "credential_profiles"
    __table_args__ = (
        CheckConstraint("port BETWEEN 1 AND 65535", name="valid_port"),
        CheckConstraint(
            "(credential_type = 'snmp_v2c' AND username IS NULL) OR "
            "(credential_type = 'routeros_api' AND username IS NOT NULL)",
            name="valid_username",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    credential_type: Mapped[CredentialType] = mapped_column(
        Enum(
            CredentialType,
            name="credential_type",
            native_enum=False,
            length=20,
            create_constraint=True,
            values_callable=lambda e: [member.value for member in e],
        )
    )
    username: Mapped[str | None] = mapped_column(String(120))
    secret_ciphertext: Mapped[str] = mapped_column(Text)
    port: Mapped[int] = mapped_column(Integer)
    verify_tls: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )

    devices: Mapped[list["Device"]] = relationship(back_populates="credential_profile")
