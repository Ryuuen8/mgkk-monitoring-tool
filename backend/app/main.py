from fastapi import FastAPI, Request
from fastapi.responses import Response
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
