from pydantic import BaseModel, Field, model_validator

from app.models.credentials import (
    CredentialType,
    SnmpAuthProtocol,
    SnmpPrivacyProtocol,
)
from app.schemas.common import ORMModel, Timestamps


class CredentialProfileRef(ORMModel):
    id: int
    name: str
    credential_type: CredentialType


class CredentialProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    credential_type: CredentialType
    username: str | None = Field(default=None, max_length=120)
    secret: str = Field(min_length=1, max_length=4096)
    auth_protocol: SnmpAuthProtocol | None = None
    privacy_protocol: SnmpPrivacyProtocol | None = None
    privacy_secret: str | None = Field(default=None, min_length=1, max_length=4096)
    port: int | None = Field(default=None, ge=1, le=65535)
    verify_tls: bool = True

    @model_validator(mode="after")
    def validate_auth_fields(self) -> "CredentialProfileCreate":
        if self.credential_type is CredentialType.SNMP_V2C:
            if self.username is not None or self.auth_protocol or self.privacy_protocol:
                raise ValueError("SNMP v2c profiles use a community string only")
            if self.privacy_secret is not None:
                raise ValueError("SNMP v2c profiles do not use a privacy secret")
        elif self.credential_type is CredentialType.SNMP_V3:
            if not self.username or self.auth_protocol is None:
                raise ValueError("SNMP v3 requires a username and auth protocol")
            if len(self.secret.encode("utf-8")) < 8:
                raise ValueError("SNMP v3 authentication passphrases need 8 bytes")
            if self.privacy_protocol is None:
                raise ValueError("SNMP v3 requires a privacy protocol selection")
            if (
                self.privacy_secret is not None
                and len(self.privacy_secret.encode("utf-8")) < 8
            ):
                raise ValueError("SNMP v3 privacy passphrases need 8 bytes")
            if (self.privacy_protocol is SnmpPrivacyProtocol.AES128) != (
                self.privacy_secret is not None
            ):
                raise ValueError("AES-128 privacy requires a privacy secret")
        elif not self.username:
            raise ValueError("RouterOS API profiles require a username")
        elif (
            self.auth_protocol is not None
            or self.privacy_protocol is not None
            or self.privacy_secret is not None
        ):
            raise ValueError("SNMP security options only apply to SNMP v3")
        return self


class CredentialProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    credential_type: CredentialType | None = None
    username: str | None = Field(default=None, max_length=120)
    secret: str | None = Field(default=None, min_length=1, max_length=4096)
    auth_protocol: SnmpAuthProtocol | None = None
    privacy_protocol: SnmpPrivacyProtocol | None = None
    privacy_secret: str | None = Field(default=None, min_length=1, max_length=4096)
    port: int | None = Field(default=None, ge=1, le=65535)
    verify_tls: bool | None = None


class CredentialProfileRead(Timestamps):
    id: int
    name: str
    credential_type: CredentialType
    username: str | None
    auth_protocol: SnmpAuthProtocol | None
    privacy_protocol: SnmpPrivacyProtocol | None
    port: int
    verify_tls: bool
    secret_configured: bool = True
    privacy_secret_configured: bool = False
