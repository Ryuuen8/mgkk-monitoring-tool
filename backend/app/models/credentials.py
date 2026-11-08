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
    SNMP_V3 = "snmp_v3"
    ROUTEROS_API = "routeros_api"


class SnmpAuthProtocol(str, enum.Enum):
    SHA = "sha"
    SHA256 = "sha256"


class SnmpPrivacyProtocol(str, enum.Enum):
    NONE = "none"
    AES128 = "aes128"


class CredentialProfile(TimestampMixin, Base):
    __tablename__ = "credential_profiles"
    __table_args__ = (
        CheckConstraint("port BETWEEN 1 AND 65535", name="valid_port"),
        CheckConstraint(
            "(credential_type = 'snmp_v2c' AND username IS NULL AND "
            "auth_protocol IS NULL AND privacy_protocol IS NULL) OR "
            "(credential_type = 'snmp_v3' AND username IS NOT NULL AND "
            "auth_protocol IN ('sha', 'sha256') AND "
            "privacy_protocol IN ('none', 'aes128')) OR "
            "(credential_type = 'routeros_api' AND username IS NOT NULL AND "
            "auth_protocol IS NULL AND privacy_protocol IS NULL)",
            name="valid_username",
        ),
        CheckConstraint(
            "(credential_type != 'snmp_v3' AND privacy_protocol IS NULL AND "
            "privacy_secret_ciphertext IS NULL) OR "
            "(credential_type = 'snmp_v3' AND privacy_protocol = 'none' AND "
            "privacy_secret_ciphertext IS NULL) OR "
            "(credential_type = 'snmp_v3' AND privacy_protocol = 'aes128' AND "
            "privacy_secret_ciphertext IS NOT NULL)",
            name="valid_privacy",
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
    auth_protocol: Mapped[SnmpAuthProtocol | None] = mapped_column(
        Enum(
            SnmpAuthProtocol,
            name="snmp_auth_protocol",
            native_enum=False,
            length=20,
            create_constraint=True,
            values_callable=lambda e: [member.value for member in e],
        )
    )
    privacy_protocol: Mapped[SnmpPrivacyProtocol | None] = mapped_column(
        Enum(
            SnmpPrivacyProtocol,
            name="snmp_privacy_protocol",
            native_enum=False,
            length=20,
            create_constraint=True,
            values_callable=lambda e: [member.value for member in e],
        )
    )
    privacy_secret_ciphertext: Mapped[str | None] = mapped_column(Text)
    port: Mapped[int] = mapped_column(Integer)
    verify_tls: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )

    devices: Mapped[list["Device"]] = relationship(back_populates="credential_profile")

    @property
    def privacy_secret_configured(self) -> bool:
        return self.privacy_secret_ciphertext is not None
