from fastapi import FastAPI, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from starlette.middleware.base import RequestResponseEndpoint

from app.api.routes import credential_profiles, device_groups, devices, sites, v1

app = FastAPI(title="MGKK Monitoring API")
app.include_router(sites.router, prefix="/api/v1")
app.include_router(sites.router, prefix="/api")
app.include_router(v1.router)
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
