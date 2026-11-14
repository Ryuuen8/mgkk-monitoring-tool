"""Alertmanager webhook ingestion, acknowledgement, maintenance, and silences."""

from datetime import UTC, datetime, timedelta

import pytest
from app.api.routes import alerts as alerts_module
from httpx import AsyncClient


def _body(
    *,
    site_code: str,
    device_id: str,
    device_name: str,
    fingerprint: str = "fp-1",
    status: str = "firing",
    severity: str = "critical",
    alertname: str = "DeviceDown",
    starts_at: datetime | None = None,
) -> dict:
    now = datetime.now(UTC)
    starts = starts_at or now - timedelta(minutes=5)
    return {
        "version": "4",
        "status": status,
        "receiver": "mgkk",
        "alerts": [
            {
                "status": status,
                "labels": {
                    "alertname": alertname,
                    "device": device_name,
                    "device_id": device_id,
                    "site": site_code,
                    "severity": severity,
                },
                "annotations": {
                    "summary": f"{alertname} on {device_name}",
                    "description": "Synthetic test alert",
                },
                "startsAt": starts.isoformat(),
                "endsAt": (
                    now.isoformat() if status == "resolved" else "0001-01-01T00:00:00Z"
                ),
                "fingerprint": fingerprint,
            }
        ],
    }


async def _site_and_device(client: AsyncClient) -> tuple[dict, dict]:
    site = (
        await client.post("/api/v1/sites", json={"code": "HQ", "name": "Headquarters"})
    ).json()
    device = (
        await client.post(
            "/api/v1/devices",
            json={
                "site_id": site["id"],
                "name": "core-rtr1",
                "ip_address": "192.0.2.10",
                "collector": "cisco",
            },
        )
    ).json()
    return site, device


async def test_webhook_ingests_firing_and_resolved_alerts(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    published: list[tuple[str, dict]] = []

    async def fake_publish(event_type: str, payload: dict) -> None:
        published.append((event_type, payload))

    monkeypatch.setattr(alerts_module.events, "publish_event", fake_publish)
    site, device = await _site_and_device(client)
    payload = _body(
        site_code=site["code"],
        device_id=device["id"],
        device_name=device["name"],
    )

    response = await client.post("/api/v1/alerts/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"processed": 1, "suppressed": 0}

    listed = await client.get("/api/v1/alerts", params={"status": "firing"})
    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["alertname"] == "DeviceDown"
    assert item["device_name"] == device["name"]
    assert item["site"] == "HQ"
    assert item["severity"] == "critical"
    assert item["status"] == "firing"
    assert item["suppressed"] is False
    assert item["ends_at"] is None

    assert published[0][0] == "alert_fired"
    assert published[0][1]["device_id"] == device["id"]
    assert published[0][1]["status"] == "firing"

    resolved = await client.post(
        "/api/v1/alerts/webhook",
        json=_body(
            site_code=site["code"],
            device_id=device["id"],
            device_name=device["name"],
            status="resolved",
        ),
    )
    assert resolved.json() == {"processed": 1, "suppressed": 0}

    history = await client.get("/api/v1/alerts", params={"status": "resolved"})
    resolved_item = history.json()["items"][0]
    assert resolved_item["id"] == item["id"]
    assert resolved_item["status"] == "resolved"
    assert resolved_item["ends_at"] is not None
    assert published[-1][0] == "alert_resolved"


async def test_webhook_respects_open_maintenance_windows(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    created: list[list[dict]] = []
    expired: list[str] = []
    counter = {"value": 0}
    published: list[tuple[str, dict]] = []

    async def fake_create(
        matchers: list[dict],
        _starts_at: datetime,
        _ends_at: datetime,
        *,
        created_by: str,
        comment: str,
    ) -> str:
        created.append(matchers)
        counter["value"] += 1
        return f"silence-{counter['value']}"

    async def fake_expire(silence_id: str) -> None:
        expired.append(silence_id)

    async def fake_publish(event_type: str, payload: dict) -> None:
        published.append((event_type, payload))

    monkeypatch.setattr(alerts_module.alertmanager, "create_silence", fake_create)
    monkeypatch.setattr(alerts_module.alertmanager, "expire_silence", fake_expire)
    monkeypatch.setattr(alerts_module.events, "publish_event", fake_publish)

    site, device = await _site_and_device(client)
    now = datetime.now(UTC)
    window = await client.post(
        "/api/v1/maintenance-windows",
        json={
            "name": "Core firmware upgrade",
            "scope_type": "device",
            "target_id": device["id"],
            "starts_at": (now - timedelta(hours=1)).isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
            "suppress_notifications": True,
            "created_by": "netops",
        },
    )
    assert window.status_code == 201, window.text
    window_body = window.json()
    assert window_body["silence_ids"] == ["silence-1"]
    assert window_body["device_id"] == device["id"]
    assert created == [[{"name": "device", "value": device["name"]}]]

    ingested = await client.post(
        "/api/v1/alerts/webhook",
        json=_body(
            site_code=site["code"],
            device_id=device["id"],
            device_name=device["name"],
        ),
    )
    assert ingested.json() == {"processed": 1, "suppressed": 1}
    assert published == []

    listed = await client.get("/api/v1/alerts")
    assert listed.json()["items"][0]["suppressed"] is True

    extended = await client.patch(
        f"/api/v1/maintenance-windows/{window_body['id']}",
        json={"ends_at": (now + timedelta(hours=2)).isoformat()},
    )
    assert extended.status_code == 200
    assert expired == ["silence-1"]
    assert extended.json()["silence_ids"] == ["silence-2"]

    deleted = await client.delete(f"/api/v1/maintenance-windows/{window_body['id']}")
    assert deleted.status_code == 204
    assert expired == ["silence-1", "silence-2"]
    assert (await client.get("/api/v1/maintenance-windows")).json()["total"] == 0


async def test_maintenance_window_validation_and_target_lookup(
    client: AsyncClient,
):
    now = datetime.now(UTC)
    invalid = await client.post(
        "/api/v1/maintenance-windows",
        json={
            "name": "Backwards",
            "scope_type": "site",
            "target_id": "00000000-0000-0000-0000-000000000001",
            "starts_at": now.isoformat(),
            "ends_at": (now - timedelta(hours=1)).isoformat(),
        },
    )
    assert invalid.status_code == 422

    missing = await client.post(
        "/api/v1/maintenance-windows",
        json={
            "name": "Missing device",
            "scope_type": "device",
            "target_id": "00000000-0000-0000-0000-000000000002",
            "starts_at": now.isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
        },
    )
    assert missing.status_code == 404


async def test_acknowledge_alert_and_list_filters(client: AsyncClient):
    site, device = await _site_and_device(client)
    await client.post(
        "/api/v1/alerts/webhook",
        json=_body(
            site_code=site["code"],
            device_id=device["id"],
            device_name=device["name"],
            fingerprint="fp-critical",
        ),
    )
    await client.post(
        "/api/v1/alerts/webhook",
        json=_body(
            site_code=site["code"],
            device_id=device["id"],
            device_name=device["name"],
            fingerprint="fp-warning",
            severity="warning",
            alertname="HighLatency",
        ),
    )

    alerts = await client.get("/api/v1/alerts")
    assert alerts.json()["total"] == 2
    target = next(
        item for item in alerts.json()["items"] if item["alertname"] == "DeviceDown"
    )

    acked = await client.post(
        f"/api/v1/alerts/{target['id']}/ack",
        json={"acknowledged_by": "netops"},
    )
    assert acked.status_code == 200
    assert acked.json()["acknowledged_by"] == "netops"
    assert acked.json()["acknowledged_at"] is not None

    acked_list = await client.get("/api/v1/alerts", params={"acknowledged": "true"})
    assert acked_list.json()["total"] == 1
    pending = await client.get("/api/v1/alerts", params={"acknowledged": "false"})
    assert pending.json()["total"] == 1

    warnings = await client.get("/api/v1/alerts", params={"severity": "warning"})
    assert warnings.json()["total"] == 1
    by_site = await client.get("/api/v1/alerts", params={"site": "HQ"})
    assert by_site.json()["total"] == 2
    by_device = await client.get("/api/v1/alerts", params={"device_id": device["id"]})
    assert by_device.json()["total"] == 2

    missing = await client.post(
        "/api/v1/alerts/00000000-0000-0000-0000-000000000003/ack"
    )
    assert missing.status_code == 404


async def test_silence_endpoints_forward_to_alertmanager(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    observed: dict[str, object] = {}

    async def fake_create(
        matchers: list[dict],
        starts_at: datetime,
        ends_at: datetime,
        *,
        created_by: str,
        comment: str,
    ) -> str:
        observed.update(
            matchers=matchers,
            created_by=created_by,
            comment=comment,
        )
        return "silence-abc"

    async def fake_list() -> list[dict]:
        return [{"id": "silence-abc", "status": {"state": "active"}}]

    expired: list[str] = []

    async def fake_expire(silence_id: str) -> None:
        expired.append(silence_id)

    monkeypatch.setattr(alerts_module.alertmanager, "create_silence", fake_create)
    monkeypatch.setattr(alerts_module.alertmanager, "list_silences", fake_list)
    monkeypatch.setattr(alerts_module.alertmanager, "expire_silence", fake_expire)

    now = datetime.now(UTC)
    created = await client.post(
        "/api/v1/silences",
        json={
            "matchers": [{"name": "device", "value": "core-rtr1"}],
            "starts_at": now.isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
            "created_by": "netops",
            "comment": "Testing",
        },
    )
    assert created.status_code == 201
    assert created.json() == {"silenceID": "silence-abc"}
    assert observed["matchers"] == [
        {"name": "device", "value": "core-rtr1", "isRegex": False}
    ]

    listed = await client.get("/api/v1/silences")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == "silence-abc"

    assert (await client.delete("/api/v1/silences/silence-abc")).status_code == 204
    assert expired == ["silence-abc"]

    async def unavailable() -> list[dict]:
        raise alerts_module.alertmanager.AlertmanagerError("unreachable")

    monkeypatch.setattr(alerts_module.alertmanager, "list_silences", unavailable)
    assert (await client.get("/api/v1/silences")).status_code == 503
