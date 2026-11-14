"""Compatibility import for the old RouterOS-only snapshot model."""

from app.models.device_snapshot import DeviceSnapshot

# Legacy name retained for callers that adopted the RouterOS-specific model.
RouterOSSnapshot = DeviceSnapshot

__all__ = ["DeviceSnapshot", "RouterOSSnapshot"]
