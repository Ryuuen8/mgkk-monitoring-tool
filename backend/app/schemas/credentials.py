from pydantic import BaseModel, Field, model_validator

from app.models.credentials import CredentialType
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
    port: int | None = Field(default=None, ge=1, le=65535)
    verify_tls: bool = True

    @model_validator(mode="after")
    def validate_auth_fields(self) -> "CredentialProfileCreate":
        if (
            self.credential_type is CredentialType.SNMP_V2C
            and self.username is not None
        ):
            raise ValueError("SNMP v2c profiles do not use a username")
        if (
            self.credential_type is CredentialType.ROUTEROS_API
            and not self.username
        ):
            raise ValueError("RouterOS API profiles require a username")
        return self


class CredentialProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    credential_type: CredentialType | None = None
    username: str | None = Field(default=None, max_length=120)
    secret: str | None = Field(default=None, min_length=1, max_length=4096)
    port: int | None = Field(default=None, ge=1, le=65535)
    verify_tls: bool | None = None


class CredentialProfileRead(Timestamps):
    id: int
    name: str
    credential_type: CredentialType
    username: str | None
    port: int
    verify_tls: bool
    secret_configured: bool = True
