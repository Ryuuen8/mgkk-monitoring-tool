"""Device telemetry collector interface and registry."""

from app.collectors.base import CollectionResult, Collector
from app.collectors.registry import get_collector

__all__ = ["CollectionResult", "Collector", "get_collector"]
