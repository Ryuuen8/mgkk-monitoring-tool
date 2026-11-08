"""API tests for device status and Prometheus-backed chart data."""

from typing import Any

from app.services import prometheus
from httpx import AsyncClient

DEVICE = "metrics-rtr1"
SITE_CODE = "MET"


async def make_device(client: AsyncClient, name: str = DEVICE) -> dict[str, Any]:
    site = await client.post(
        "/api/sites", json={"code": SITE_CODE, "name": "Metrics site"}
    )
    assert site.status_code == 201
    response = await client.post(
        "/api/devices",
        json={"site_id": site.json()["id"], "name": name, "mgmt_ip": "10.20.0.1"},
    )
    assert response.status_code == 201
    return response.json()


def instant(value: str) -> list[dict[str, Any]]:
    return [
        {
            "metric": {"device": DEVICE, "site": SITE_CODE},
            "value": [1_700_000_000, value],
        }
    ]


async def test_health_alias(client: AsyncClient):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_status_merges_prometheus_samples(
    client: AsyncClient, monkeypatch
):
    await make_device(client)

    async def fake_query(expression: str) -> list[dict[str, Any]]:
        return {
            "device_up": instant("1"),
            "ping_latency_seconds": instant("0.0125"),
            "ping_packet_loss_ratio": instant("0.25"),
        }[expression]

    monkeypatch.setattr(prometheus, "query", fake_query)

    response = await client.get("/api/devices/status")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["name"] == DEVICE
    assert item["site_code"] == SITE_CODE
    assert item["up"] is True
    assert item["latency_ms"] == 12.5
    assert item["packet_loss"] == 0.25


async def test_status_reports_down_and_nan_as_null(
    client: AsyncClient, monkeypatch
):
    await make_device(client)

    async def fake_query(expression: str) -> list[dict[str, Any]]:
        return {
            "device_up": instant("0"),
            "ping_latency_seconds": instant("NaN"),
            "ping_packet_loss_ratio": instant("1"),
        }[expression]

    monkeypatch.setattr(prometheus, "query", fake_query)

    item = (await client.get("/api/devices/status")).json()["items"][0]
    assert item["up"] is False
    assert item["latency_ms"] is None
    assert item["packet_loss"] == 1.0


async def test_status_degrades_when_prometheus_is_down(
    client: AsyncClient, monkeypatch
):
    await make_device(client)

    async def failing_query(expression: str) -> list[dict[str, Any]]:
        raise prometheus.PrometheusError("connection refused")

    monkeypatch.setattr(prometheus, "query", failing_query)

    response = await client.get("/api/devices/status")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["name"] == DEVICE
    assert item["up"] is None
    assert item["latency_ms"] is None


async def test_device_metrics_returns_finite_points(
    client: AsyncClient, monkeypatch
):
    device = await make_device(client)

    async def fake_range(
        expression: str, *, start, end, step_seconds: int
    ) -> list[dict[str, Any]]:
        values = {
            "ping_latency_seconds": [
                [1_700_000_000, "0.010"],
                [1_700_000_030, "0.020"],
                [1_700_000_060, "NaN"],
            ],
            "device_up": [[1_700_000_000, "1"], [1_700_000_030, "0"]],
            "ping_packet_loss_ratio": [[1_700_000_000, "0"]],
        }
        metric = expression.split("{")[0]
        return [{"metric": {"device": DEVICE}, "values": values[metric]}]

    monkeypatch.setattr(prometheus, "query_range", fake_range)

    response = await client.get(
        f"/api/devices/{device['id']}/metrics",
        params={"range_minutes": 30, "step_seconds": 15},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["device_id"] == device["id"]
    assert body["name"] == DEVICE
    assert body["site_code"] == SITE_CODE
    assert body["range_seconds"] == 1800
    assert body["step_seconds"] == 15
    # The NaN sample is dropped, not serialized.
    assert body["latency"] == [
        {"t": 1_700_000_000.0, "value": 0.01},
        {"t": 1_700_000_030.0, "value": 0.02},
    ]
    assert [point["value"] for point in body["uptime"]] == [1.0, 0.0]
    assert len(body["packet_loss"]) == 1


async def test_device_metrics_missing_device_returns_404(client: AsyncClient):
    response = await client.get("/api/devices/999/metrics")
    assert response.status_code == 404
    assert response.json()["detail"] == "device not found"


async def test_device_metrics_prometheus_failure_returns_502(
    client: AsyncClient, monkeypatch
):
    device = await make_device(client)

    async def failing_range(*args, **kwargs) -> list[dict[str, Any]]:
        raise prometheus.PrometheusError("connection refused")

    monkeypatch.setattr(prometheus, "query_range", failing_range)

    response = await client.get(f"/api/devices/{device['id']}/metrics")
    assert response.status_code == 502
    assert "prometheus query failed" in response.json()["detail"]
