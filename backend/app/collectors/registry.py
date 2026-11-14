from app.collectors.base import BaseCollector
from app.collectors.cisco import CiscoCollector
from app.collectors.generic import GenericCollector
from app.collectors.mikrotik import MikroTikCollector
from app.models import CollectorType

_COLLECTORS: dict[CollectorType, BaseCollector] = {
    CollectorType.GENERIC: GenericCollector(),
    CollectorType.MIKROTIK: MikroTikCollector(),
    CollectorType.CISCO: CiscoCollector(),
}


def get_collector(collector: CollectorType) -> BaseCollector:
    try:
        return _COLLECTORS[collector]
    except KeyError as exc:
        raise ValueError(f"unsupported collector: {collector}") from exc
