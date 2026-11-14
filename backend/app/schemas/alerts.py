"""Schemas for alerts, maintenance windows, silences, and live events."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

MaintenanceScope = Literal["device", "group", "site"]


class AlertmanagerAlert(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: str
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: datetime | None = Field(default=None, alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    fingerprint: str | None = None
    generator_url: str | None = Field(default=None, alias="generatorURL")


class AlertmanagerWebhook(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: str | None = None
    status: str | None = None
    receiver: str | None = None
    group_key: str | None = Field(default=None, alias="groupKey")
    alerts: list[AlertmanagerAlert] = Field(default_factory=list)


class AlertEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(validation_alias="public_id")
    fingerprint: str
    alertname: str
    device_name: str | None
    site: str | None
    severity: str
    status: str
    starts_at: datetime
    ends_at: datetime | None
    summary: str | None
    description: str | None
    labels: dict[str, Any]
    annotations: dict[str, Any]
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    suppressed: bool
    last_received_at: datetime
    created_at: datetime
    updated_at: datetime


class AlertAcknowledge(BaseModel):
    acknowledged_by: str | None = Field(default=None, max_length=120)


class WebhookResult(BaseModel):
    processed: int
    suppressed: int


class MaintenanceWindowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    scope_type: MaintenanceScope
    target_id: UUID
    starts_at: datetime
    ends_at: datetime
    suppress_notifications: bool = True
    created_by: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_window(self) -> "MaintenanceWindowCreate":
        if self.ends_at <= self.starts_at:
            raise ValueError("maintenance window must end after it starts")
        return self


class MaintenanceWindowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    suppress_notifications: bool | None = None


class MaintenanceWindowRead(BaseModel):
    id: UUID
    name: str
    description: str | None
    scope_type: str
    device_id: UUID | None
    group_id: UUID | None
    site_id: UUID | None
    starts_at: datetime
    ends_at: datetime
    suppress_notifications: bool
    silence_ids: list[str]
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class SilenceMatcher(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=255)
    is_regex: bool = Field(default=False, alias="isRegex")

    model_config = ConfigDict(populate_by_name=True)


class SilenceCreate(BaseModel):
    matchers: list[SilenceMatcher] = Field(min_length=1)
    starts_at: datetime
    ends_at: datetime
    created_by: str = Field(min_length=1, max_length=120)
    comment: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_window(self) -> "SilenceCreate":
        if self.ends_at <= self.starts_at:
            raise ValueError("silence must end after it starts")
        return self


class SyslogEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(validation_alias="public_id")
    device_id: int | None
    source_ip: str
    facility: int
    severity: int
    hostname: str | None
    app_name: str | None
    event_type: str
    message: str
    occurred_at: datetime
    created_at: datetime

    @field_validator("source_ip", mode="before")
    @classmethod
    def _stringify_ip(cls, value: Any) -> Any:
        return str(value) if value is not None else value
