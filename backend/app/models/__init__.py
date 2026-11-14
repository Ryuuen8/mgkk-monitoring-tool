"""Import every model here so Base.metadata (and Alembic) sees all tables."""

from app.models.credentials import CredentialProfile, CredentialType
from app.models.device import Device
from app.models.device_group import DeviceGroup, device_group_members
from app.models.device_neighbor import DeviceNeighbor
from app.models.device_snapshot import DeviceSnapshot
from app.models.enums import CollectorType, DeviceCheckType, DeviceType
from app.models.interface import NetworkInterface
from app.models.routeros_snapshot import RouterOSSnapshot
from app.models.site import Site

__all__ = [
    "CollectorType",
    "CredentialProfile",
    "CredentialType",
    "Device",
    "DeviceCheckType",
    "DeviceGroup",
    "DeviceNeighbor",
    "DeviceSnapshot",
    "DeviceType",
    "NetworkInterface",
    "RouterOSSnapshot",
    "Site",
    "device_group_members",
]
