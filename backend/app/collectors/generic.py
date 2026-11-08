from app.collectors.base import CollectionResult
from app.models import Device, DeviceCheckType


class GenericCollector:
    async def collect(self, device: Device) -> CollectionResult:
        if device.check_type is not DeviceCheckType.SNMP:
            raise ValueError("the generic collector requires an SNMP check")

        from app.worker import poll_snmp_telemetry

        return CollectionResult(interfaces=await poll_snmp_telemetry(device))
