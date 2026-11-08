"""Unit tests for the DB-driven ping poller (uses the test database)."""

import math
from datetime import UTC, datetime

import pytest
from app.models import CredentialProfile, CredentialType, Device, Site
from app.services.credentials import encrypt_secret
from app.worker import (
    DEVICE_UP,
    PING_LATENCY,
    PING_PACKET_LOSS,
    PingResult,
    configured_check,
    list_poll_targets,
    poll_device,
    poll_due_devices,
)
from cryptography.fernet import Fernet

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


async def make_site(session, code: str = "W") -> Site:
    site = Site(code=code, name=f"Site {code}")
    session.add(site)
    await session.flush()
    return site


async def make_device(session, site: Site, name: str, **overrides) -> Device:
    data = {
        "site_id": site.id,
        "name": name,
        "mgmt_ip": "10.30.0.1",
        "poll_interval_seconds": 60,
    }
    data.update(overrides)
    device = Device(**data)
    session.add(device)
    await session.commit()
    return device


async def test_poll_due_devices_updates_status_and_metrics(session):
    site = await make_site(session)
    device = await make_device(session, site, "worker-rtr1")
    second = await make_device(session, site, "worker-rtr2", mgmt_ip="10.30.0.2")

    calls: list[str] = []

    async def fake_ping(address: str) -> PingResult:
        calls.append(address)
        return PingResult(is_alive=True, avg_rtt=0.012, packet_loss=0.25)

    last_polled: dict[int, float] = {}
    polled = await poll_due_devices(
        session,
        fake_ping,
        last_polled=last_polled,
        now_monotonic=100.0,
        now=NOW,
    )

    assert polled == [device.id, second.id]
    assert calls == ["10.30.0.1", "10.30.0.2"]
    assert last_polled[device.id] == 100.0
    assert device.last_seen_at == NOW

    labels = ("worker-rtr1", site.code)
    assert DEVICE_UP.labels(*labels)._value.get() == 1.0
    assert PING_LATENCY.labels(*labels)._value.get() == pytest.approx(0.012)
    assert PING_PACKET_LOSS.labels(*labels)._value.get() == pytest.approx(0.25)


async def test_poll_due_devices_respects_each_interval(session):
    site = await make_site(session, "I")
    device = await make_device(session, site, "worker-interval", poll_interval_seconds=60)

    async def fake_ping(address: str) -> PingResult:
        return PingResult(is_alive=True, avg_rtt=0.001, packet_loss=0.0)

    last_polled = {device.id: 100.0}

    # 30 seconds later: not due yet.
    assert (
        await poll_due_devices(
            session,
            fake_ping,
            last_polled=last_polled,
            now_monotonic=130.0,
        )
        == []
    )

    # 60 seconds later: due again.
    assert await poll_due_devices(
        session, fake_ping, last_polled=last_polled, now_monotonic=160.0
    ) == [device.id]
    assert last_polled[device.id] == 160.0


async def test_failed_ping_marks_device_down_without_timestamp(session):
    site = await make_site(session, "D")
    device = await make_device(session, site, "worker-down")

    async def fake_ping(address: str) -> PingResult:
        return PingResult(
            is_alive=False, avg_rtt=float("nan"), packet_loss=1.0
        )

    assert await poll_due_devices(
        session, fake_ping, last_polled={}, now_monotonic=10.0
    ) == [device.id]

    labels = ("worker-down", site.code)
    assert DEVICE_UP.labels(*labels)._value.get() == 0.0
    assert math.isnan(PING_LATENCY.labels(*labels)._value.get())
    assert PING_PACKET_LOSS.labels(*labels)._value.get() == 1.0
    assert device.last_seen_at is None


async def test_pinger_exception_marks_device_down(session):
    site = await make_site(session, "E")
    await make_device(session, site, "worker-error")
    device = (await list_poll_targets(session))[0]

    async def boom(address: str) -> PingResult:
        raise OSError("network unreachable")

    result = await poll_device(session, device, boom)

    assert result.is_alive is False
    assert result.packet_loss == 1.0
    assert DEVICE_UP.labels("worker-error", site.code)._value.get() == 0.0


async def test_list_poll_targets_skips_inactive_devices(session):
    site = await make_site(session, "F")
    await make_device(session, site, "worker-active")
    await make_device(session, site, "worker-paused", is_active=False)
    profile = CredentialProfile(
        name="worker-snmp-profile",
        credential_type=CredentialType.SNMP_V2C,
        secret_ciphertext="encrypted",
        port=161,
    )
    session.add(profile)
    await session.commit()
    await make_device(
        session,
        site,
        "worker-snmp",
        check_type="snmp",
        credential_profile_id=profile.id,
    )

    targets = await list_poll_targets(session)

    assert [device.name for device in targets] == [
        "worker-active",
        "worker-snmp",
    ]
    assert targets[0].site.code == "F"
    assert targets[1].credential_profile.name == "worker-snmp-profile"


async def test_configured_snmp_check_decrypts_profile_secret(
    session, monkeypatch
):
    from app import worker

    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    site = await make_site(session, "S")
    profile = CredentialProfile(
        name="snmp-check-profile",
        credential_type=CredentialType.SNMP_V2C,
        secret_ciphertext=encrypt_secret("private-community"),
        port=1161,
    )
    device = Device(
        site_id=site.id,
        name="snmp-check-device",
        mgmt_ip="192.0.2.5",
        check_type="snmp",
        credential_profile=profile,
    )
    session.add(device)
    await session.flush()

    calls = []

    async def fake_snmp(address, port, community):
        calls.append((address, port, community))
        return PingResult(is_alive=True, avg_rtt=0.01, packet_loss=0.0)

    monkeypatch.setattr(worker, "snmp_check", fake_snmp)
    result = await configured_check(device)
    assert result.is_alive
    assert calls == [("192.0.2.5", 1161, "private-community")]


async def test_routeros_api_check_uses_https_and_profile_options(monkeypatch):
    from app import worker

    calls = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *, verify, timeout):
            calls["verify"] = verify
            calls["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return None

        async def get(self, url, *, auth):
            calls["url"] = url
            calls["auth"] = auth
            return FakeResponse()

    monkeypatch.setattr(worker.httpx, "AsyncClient", FakeClient)
    result = await worker.routeros_api_check(
        "2001:db8::1",
        8443,
        "monitor",
        "router-password",
        verify_tls=False,
    )

    assert result.is_alive
    assert calls == {
        "verify": False,
        "timeout": 5.0,
        "url": "https://[2001:db8::1]:8443/rest/system/resource",
        "auth": ("monitor", "router-password"),
    }
