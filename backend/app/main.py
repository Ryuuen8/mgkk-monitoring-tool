from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from starlette.middleware.base import RequestResponseEndpoint

from app.api.routes import (
    alerts,
    credential_profiles,
    device_groups,
    devices,
    sites,
    v1,
)
from app.services.events import close_redis


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await close_redis()


app = FastAPI(title="MGKK Monitoring API", lifespan=lifespan)
app.include_router(sites.router, prefix="/api")
app.include_router(v1.router)
app.include_router(alerts.router)
app.include_router(device_groups.router, prefix="/api")
app.include_router(credential_profiles.router, prefix="/api")
app.include_router(devices.router, prefix="/api")

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
)


@app.middleware("http")
async def count_http_requests(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    response = await call_next(request)
    http_requests_total.inc()
    return response


@app.get("/health")
@app.get("/api/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
