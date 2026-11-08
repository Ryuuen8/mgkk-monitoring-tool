from dataclasses import dataclass, field
from typing import Any, Protocol

from app.models import Device


@dataclass
class CollectionResult:
    interfaces: dict[int, dict[str, Any]] = field(default_factory=dict)


class Collector(Protocol):
    async def collect(self, device: Device) -> CollectionResult: ...
