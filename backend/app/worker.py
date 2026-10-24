import logging
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def poll(target_url: str, interval: float) -> None:
    logger.info("Polling %s every %s seconds", target_url, interval)
    while True:
        try:
            with urlopen(target_url, timeout=10) as response:
                logger.info("Poll succeeded: %s returned %s", target_url, response.status)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            logger.warning("Poll failed for %s: %s", target_url, exc)
        time.sleep(interval)


if __name__ == "__main__":
    poll(
        os.getenv("POLL_TARGET_URL", "http://api:8000/health"),
        max(1.0, float(os.getenv("POLL_INTERVAL_SECONDS", "30"))),
    )
