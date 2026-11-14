"""Redis Pub/Sub event bus shared by the worker, API, and syslog receiver."""

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

EVENTS_CHANNEL = "mgkk:events"
_redis: Redis | None = None
_lock = asyncio.Lock()


def _redis_url() -> str | None:
    return os.getenv("REDIS_URL")


async def get_redis() -> Redis | None:
    """Return a shared Redis client, or None when events are not configured."""
    global _redis
    if not _redis_url():
        return None
    if _redis is None:
        async with _lock:
            if _redis is None:
                _redis = Redis.from_url(
                    _redis_url() or "",
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def publish_event(event_type: str, payload: dict[str, Any]) -> None:
    """Publish a low-cardinality state-change event (best effort)."""
    if not _redis_url():
        logger.debug("REDIS_URL is unset; dropping %s event", event_type)
        return
    event = {
        "type": event_type,
        "timestamp": datetime.now(UTC).isoformat(),
        **payload,
    }
    try:
        client = await get_redis()
        if client is None:
            return
        await client.publish(EVENTS_CHANNEL, json.dumps(event, default=str))
    except Exception as exc:  # noqa: BLE001 - events must not break polling
        logger.warning("Failed to publish %s event: %s", event_type, type(exc).__name__)
