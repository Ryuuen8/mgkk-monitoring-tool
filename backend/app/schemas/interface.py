from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import Timestamps
from app.schemas.metrics import MetricPoint


class NetworkInterfaceRead(Timestamps):
    id: int
    device_id: int
    if_index: int
    name: str
    alias: str | None
    admin_status: int | None
    oper_status: int | None
    link_speed_mbps: int | None
    link_speed_override_mbps: int | None
    last_polled_at: datetime | None


class LinkSpeedOverrideUpdate(BaseModel):
    link_speed_override_mbps: int | None = Field(default=None, gt=0)


class InterfaceMetrics(BaseModel):
    interface_id: int
    interface_name: str
    range_seconds: int
    step_seconds: int
    in_bits_per_second: list[MetricPoint]
    out_bits_per_second: list[MetricPoint]
    in_errors_per_second: list[MetricPoint]
    out_errors_per_second: list[MetricPoint]
    in_discards_per_second: list[MetricPoint]
    out_discards_per_second: list[MetricPoint]
    in_utilization: list[MetricPoint]
    out_utilization: list[MetricPoint]
