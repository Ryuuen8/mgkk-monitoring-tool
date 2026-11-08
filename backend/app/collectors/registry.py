from app.collectors.base import Collector
from app.collectors.generic import GenericCollector
from app.collectors.mikrotik import MikroTikCollector
from app.models import CollectorType

_COLLECTORS: dict[CollectorType, Collector] = {
    CollectorType.GENERIC: GenericCollector(),
    CollectorType.MIKROTIK: MikroTikCollector(),
}


def get_collector(collector: CollectorType) -> Collector:
    try:
        return _COLLECTORS[collector]
    except KeyError as exc:
        raise ValueError(f"unsupported collector: {collector}") from exc
