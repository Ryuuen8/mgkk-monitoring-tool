"""Minimal Alertmanager v2 API client for silences."""

import logging
import os
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class AlertmanagerError(RuntimeError):
    """Alertmanager is unreachable or rejected a request."""


def _base_url() -> str:
    return os.getenv("ALERTMANAGER_URL", "http://localhost:9093").rstrip("/")


def _stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


async def _request(method: str, path: str, payload: Any = None) -> Any:
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.request(method, url, json=payload)
            response.raise_for_status()
            return response.json() if response.content else None
    except (httpx.HTTPError, ValueError) as exc:
        raise AlertmanagerError(
            f"Alertmanager request failed: {type(exc).__name__}"
        ) from exc


async def create_silence(
    matchers: list[dict[str, Any]],
    starts_at: datetime,
    ends_at: datetime,
    *,
    created_by: str,
    comment: str,
) -> str:
    payload = {
        "matchers": [
            {
                "name": matcher["name"],
                "value": matcher["value"],
                "isRegex": bool(matcher.get("isRegex", False)),
            }
            for matcher in matchers
        ],
        "startsAt": _stamp(starts_at),
        "endsAt": _stamp(ends_at),
        "createdBy": created_by,
        "comment": comment,
    }
    result = await _request("POST", "/api/v2/silences", payload)
    if not isinstance(result, dict) or not result.get("silenceID"):
        raise AlertmanagerError("Alertmanager did not return a silence ID")
    return str(result["silenceID"])


async def expire_silence(silence_id: str) -> None:
    await _request(
        "DELETE",
        f"/api/v2/silence/{silence_id}",
    )


async def list_silences() -> list[dict[str, Any]]:
    result = await _request("GET", "/api/v2/silences")
    return result if isinstance(result, list) else []
