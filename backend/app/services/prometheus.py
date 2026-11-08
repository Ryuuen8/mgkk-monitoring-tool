"""Minimal async client for the Prometheus HTTP API."""

import os
from datetime import datetime

import httpx
from dotenv import load_dotenv

load_dotenv()

DEFAULT_TIMEOUT = 10.0


class PrometheusError(RuntimeError):
    """Prometheus is unreachable or returned an error response."""


def base_url() -> str:
    return os.getenv("PROMETHEUS_URL", "http://localhost:9090").rstrip("/")


def timeout() -> float:
    return float(os.getenv("PROMETHEUS_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT)))


async def _get(path: str, params: dict[str, str | float]) -> list[dict]:
    url = f"{base_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout()) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise PrometheusError(f"{url}: {exc}") from exc

    if payload.get("status") != "success":
        raise PrometheusError(payload.get("error") or "unknown Prometheus error")

    result = payload.get("data", {}).get("result")
    if not isinstance(result, list):
        raise PrometheusError("unexpected Prometheus response")
    return result


async def query(expression: str) -> list[dict]:
    """Run an instant query and return its result vector."""
    return await _get("/api/v1/query", {"query": expression})


async def query_range(
    expression: str,
    *,
    start: datetime,
    end: datetime,
    step_seconds: int,
) -> list[dict]:
    """Run a range query and return its result matrix."""
    return await _get(
        "/api/v1/query_range",
        {
            "query": expression,
            "start": start.timestamp(),
            "end": end.timestamp(),
            "step": f"{step_seconds}s",
        },
    )
