import os
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from fastapi import FastAPI, Request
from fastapi.responses import Response
from icmplib import ping  # type: ignore[import-untyped]
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

app = FastAPI(title="MGKK Monitoring API")
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ("method", "path", "status"),
)


@app.middleware("http")
async def count_http_requests(request: Request, call_next):
    response = await call_next(request)
    route = request.scope.get("route")
    http_requests_total.labels(
        request.method,
        getattr(route, "path", request.url.path),
        str(response.status_code),
    ).inc()
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/device-status")
def device_status() -> dict:
    target = os.getenv("POLL_TARGET_URL", "http://api:8000/health")
    checked_at = datetime.now(UTC).isoformat()
    if target.startswith(("http://", "https://")):
        try:
            with urlopen(target, timeout=10) as response:
                return {
                    "target": target,
                    "type": "http",
                    "status": "online",
                    "http_status": response.status,
                    "checked_at": checked_at,
                }
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            return {
                "target": target,
                "type": "http",
                "status": "offline",
                "error": str(exc),
                "checked_at": checked_at,
            }
    try:
        result = ping(target, count=3, timeout=2)
        return {
            "target": target,
            "type": "ping",
            "status": "online" if result.is_alive else "offline",
            "avg_rtt": result.avg_rtt,
            "packet_loss": result.packet_loss,
            "checked_at": checked_at,
        }
    except (OSError, ValueError, TimeoutError) as exc:
        return {
            "target": target,
            "type": "ping",
            "status": "offline",
            "error": str(exc),
            "checked_at": checked_at,
        }
