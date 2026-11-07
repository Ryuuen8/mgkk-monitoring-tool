import logging
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from icmplib import ping  # type: ignore[import-untyped]

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def poll(target: str, interval: float) -> None:
    logger.info("Monitoring %s every %s seconds", target, interval)
    while True:
        try:
            if target.startswith(("http://", "https://")):
                with urlopen(target, timeout=10) as response:
                    logger.info("HTTP poll succeeded: %s returned %s", target, response.status)
            else:
                result = ping(target, count=3, timeout=2)
                if result.is_alive:
                    logger.info(
                        "Ping succeeded: %s is alive (avg_rtt=%.2f ms, packet_loss=%.0f%%)",
                        target,
                        result.avg_rtt,
                        result.packet_loss * 100,
                    )
                else:
                    logger.warning("Ping failed for %s: host unreachable", target)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            logger.warning("Poll failed for %s: %s", target, exc)
        time.sleep(interval)


if __name__ == "__main__":
    poll(
        os.getenv("POLL_TARGET_URL", "http://api:8000/health"),
        max(1.0, float(os.getenv("POLL_INTERVAL_SECONDS", "30"))),
    )
