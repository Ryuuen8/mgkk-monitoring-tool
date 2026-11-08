from fastapi import FastAPI, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

from app.api.routes import credential_profiles, device_groups, devices, sites

app = FastAPI(title="MGKK Monitoring API")
app.include_router(sites.router, prefix="/api")
app.include_router(device_groups.router, prefix="/api")
app.include_router(credential_profiles.router, prefix="/api")
app.include_router(devices.router, prefix="/api")

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
@app.get("/api/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
