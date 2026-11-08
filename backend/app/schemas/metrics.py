"""Response models for device status and Prometheus-backed charts."""

from datetime import datetime

from pydantic import BaseModel


class MetricPoint(BaseModel):
    """One sample: unix timestamp (seconds) and value."""

    t: float
    value: float


class DeviceStatusRead(BaseModel):
    device_id: int
    name: str
    site_code: str
    up: bool | None = None
    latency_ms: float | None = None
    packet_loss: float | None = None
    last_seen_at: datetime | None = None


class DeviceStatusList(BaseModel):
    items: list[DeviceStatusRead]


class DeviceMetrics(BaseModel):
    device_id: int
    name: str
    site_code: str
    range_seconds: int
    step_seconds: int
    latency: list[MetricPoint]
    uptime: list[MetricPoint]
    packet_loss: list[MetricPoint]
