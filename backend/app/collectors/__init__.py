"""Device telemetry collector interface and registry."""

from app.collectors.base import (
    BaseCollector,
    CollectionResult,
    Collector,
    HealthData,
    InterfaceData,
    NeighborData,
    SystemInfo,
)
from app.collectors.registry import get_collector

__all__ = [
    "BaseCollector",
    "CollectionResult",
    "Collector",
    "HealthData",
    "InterfaceData",
    "NeighborData",
    "SystemInfo",
    "get_collector",
]
