"""Live event publishing (worker transitions) and WebSocket scoping/auth."""

from uuid import uuid4

import pytest
from app import worker
from app.api.routes.alerts import _ws_matches
from app.main import app
from app.models import Device, Site
from app.worker import PingResult, _publish_device_status, save_interface_telemetry
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def test_ws_matches_site_and_device_scopes():
    event = {"device": "core-rtr1", "device_id": "uuid-1", "site": "HQ"}

    assert _ws_matches(event, None, None) is True
    assert _ws_matches(event, "HQ", None) is True
    assert _ws_matches(event, None, "core-rtr1") is True
    assert _ws_matches(event, None, "uuid-1") is True
    assert _ws_matches(event, "DR", None) is False
    assert _ws_matches(event, None, "edge-rtr2") is False


def test_websocket_rejects_invalid_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WS_AUTH_TOKEN", "correct-token")

    with TestClient(app) as client:
        with (
            pytest.raises(WebSocketDisconnect) as missing,
            client.websocket_connect("/api/v1/ws/events"),
        ):
            pass
        assert missing.value.code == 4401

        with (
            pytest.raises(WebSocketDisconnect) as wrong,
            client.websocket_connect("/api/v1/ws/events?token=wrong-token"),
        ):
            pass
        assert wrong.value.code == 4401


async def test_device_status_publishes_only_on_transition(
    monkeypatch: pytest.MonkeyPatch,
):
    published: list[tuple[str, dict]] = []

    async def fake_publish(event_type: str, payload: dict) -> None:
        published.append((event_type, payload))

    monkeypatch.setattr(worker.events, "publish_event", fake_publish)
    worker._last_device_status.clear()
    device = type(
        "DeviceStub",
        (),
        {
            "id": 7,
            "name": "core-rtr1",
            "public_id": uuid4(),
            "site": type("SiteStub", (), {"code": "HQ"})(),
        },
    )()
    up = PingResult(is_alive=True, avg_rtt=0.0125, packet_loss=0.0)
    down = PingResult(is_alive=False, avg_rtt=float("inf"), packet_loss=1.0)

    await _publish_device_status(device, up)
    await _publish_device_status(device, up)
    await _publish_device_status(device, down)
    await _publish_device_status(device, down)

    assert [item[0] for item in published] == ["device_status", "device_status"]
    assert published[0][1]["up"] is True
    assert published[0][1]["latency_ms"] == 12.5
    assert published[0][1]["device_id"] == str(device.public_id)
    assert published[1][1]["up"] is False
    assert published[1][1]["latency_ms"] is None
    assert published[1][1]["packet_loss_percent"] == 100.0


async def test_interface_telemetry_publishes_admin_or_oper_changes(
    session, monkeypatch: pytest.MonkeyPatch
):
    published: list[tuple[str, dict]] = []

    async def fake_publish(event_type: str, payload: dict) -> None:
        published.append((event_type, payload))

    monkeypatch.setattr(worker.events, "publish_event", fake_publish)

    site = Site(code="HQ", name="Headquarters")
    session.add(site)
    await session.flush()
    device = Device(
        site_id=site.id,
        site=site,
        name="core-rtr1",
        mgmt_ip="192.0.2.10",
        poll_interval_seconds=60,
    )
    session.add(device)
    await session.commit()

    base = {
        "name": "Gi0/1",
        "alias": "uplink",
        "admin": 1,
        "oper": 1,
        "speed": 1000,
        "in_octets": 100,
        "out_octets": 100,
        "in_errors": 0,
        "out_errors": 0,
        "in_discards": 0,
        "out_discards": 0,
        "crc_errors": 0,
    }
    await save_interface_telemetry(session, device, {1: base})
    assert published == []

    await save_interface_telemetry(session, device, {1: {**base, "oper": 2}})

    assert len(published) == 1
    event_type, payload = published[0]
    assert event_type == "interface_status"
    assert payload["interface"] == "Gi0/1"
    assert payload["admin_status"] == 1
    assert payload["oper_status"] == 2
    assert payload["up"] is False
    assert payload["device_id"] == str(device.public_id)
    assert payload["site"] == "HQ"
