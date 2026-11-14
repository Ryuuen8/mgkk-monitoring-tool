"""Import every model here so Base.metadata (and Alembic) sees all tables."""

from app.models.alerting import AlertEvent, MaintenanceWindow
from app.models.credentials import CredentialProfile, CredentialType
from app.models.device import Device
from app.models.device_group import DeviceGroup, device_group_members
from app.models.device_neighbor import DeviceNeighbor
from app.models.device_snapshot import DeviceSnapshot
from app.models.enums import (
    CollectorType,
    DeviceCheckType,
    DeviceType,
    OsFamily,
)
from app.models.interface import NetworkInterface
from app.models.routeros_snapshot import RouterOSSnapshot
from app.models.site import Site
from app.models.syslog import SyslogEvent

__all__ = [
    "AlertEvent",
    "CollectorType",
    "CredentialProfile",
    "CredentialType",
    "Device",
    "DeviceCheckType",
    "DeviceGroup",
    "DeviceNeighbor",
    "DeviceSnapshot",
    "DeviceType",
    "MaintenanceWindow",
    "NetworkInterface",
    "OsFamily",
    "RouterOSSnapshot",
    "Site",
    "SyslogEvent",
    "device_group_members",
]
