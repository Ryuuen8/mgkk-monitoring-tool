"""Unit tests for the DB-driven ping poller (uses the test database)."""

import math
from datetime import UTC, datetime, timedelta

import pytest
from app.models import (
    CredentialProfile,
    CredentialType,
    Device,
    DeviceNeighbor,
    DeviceSnapshot,
    NetworkInterface,
    Site,
)
from app.services.credentials import encrypt_secret
from app.worker import (
    DEVICE_LATENCY_MS,
    DEVICE_UP,
    INTERFACE_CRC_ERRORS,
    INTERFACE_IN_BYTES,
    INTERFACE_IN_UTILIZATION_PERCENT,
    PACKET_LOSS_PERCENT,
    PING_LATENCY,
    PING_PACKET_LOSS,
    PingResult,
    _aggregate_host_resources,
    _counter_delta,
    configured_check,
    list_poll_targets,
    poll_device,
    poll_due_devices,
    save_device_snapshots,
    save_interface_telemetry,
    save_neighbors,
)
from cryptography.fernet import Fernet
from sqlalchemy import select

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def test_aggregate_host_resources_uses_average_cpu_and_ram_storage():
    cpu, total_memory, used_memory = _aggregate_host_resources(
        processor_loads={1: 20, 2: 80},
        storage_types={1: 2, 2: 4, 3: 2},
        storage_allocation_units={1: 1024, 2: 1024, 3: 4096},
        storage_sizes={1: 1000, 2: 2048, 3: 10},
        storage_used={1: 400, 2: 1900, 3: 5},
    )

    assert cpu == 50
    assert total_memory == 1_064_960
    assert used_memory == 430_080


def test_aggregate_host_resources_reports_missing_tables_as_unavailable():
    assert _aggregate_host_resources({}, {}, {}, {}, {}) == (None, None, None)


async def test_poll_host_resources_reads_standard_mib_tables(monkeypatch):
    from app import worker

    tables = {
        "1.3.6.1.2.1.25.3.3.1.2": {1: 20, 2: 80},
        "1.3.6.1.2.1.25.2.3.1.2": {1: 2},
        "1.3.6.1.2.1.25.2.3.1.4": {1: 1024},
        "1.3.6.1.2.1.25.2.3.1.5": {1: 1000},
        "1.3.6.1.2.1.25.2.3.1.6": {1: 400},
    }
    walked_oids = []

    async def fake_snmp_walk(engine, auth, target, oid):
        walked_oids.append(oid)
        return tables[oid]

    monkeypatch.setattr(worker, "_snmp_walk", fake_snmp_walk)

    metrics = await worker._poll_host_resources(None, None, None, "generic")

    assert metrics == (50, 1_024_000, 409_600)
    assert len(walked_oids) == 5


@pytest.mark.parametrize(
    ("current", "previous", "bits", "expected"),
    [
        (15, 10, 64, 5),
        (3, 10, 64, 3),
        (10, None, 64, 0),
        (3, (1 << 64) - 2, 64, 5),
        (2, (1 << 32) - 1, 32, 3),
    ],
)
def test_counter_delta_handles_increments_resets_and_baselines(
    current, previous, bits, expected
):
    assert _counter_delta(current, previous, bits=bits) == expected


async def test_interface_telemetry_persists_snapshots_and_exports_counter_delta(
    session,
):
    site = await make_site(session, "IT")
    device = Device(
        site_id=site.id,
        site=site,
        name="telemetry-counter-test",
        mgmt_ip="10.30.0.10",
    )
    session.add(device)
    await session.flush()
    labels = (device.name, "ether1", site.code)
    counter = INTERFACE_IN_BYTES.labels(*labels)
    initial_total = counter._value.get()
    crc_counter = INTERFACE_CRC_ERRORS.labels(*labels)
    initial_crc_total = crc_counter._value.get()

    await save_interface_telemetry(
        session,
        device,
        {
            1: {
                "name": "ether1",
                "alias": "uplink",
                "admin": 1,
                "oper": 1,
                "speed": 0,
                "in_octets": 100,
                "out_octets": 200,
                "in_errors": 2,
                "out_errors": 0,
                "in_discards": 0,
                "out_discards": 1,
                "crc_errors": 1,
            }
        },
    )
    row = await session.scalar(
        select(NetworkInterface).where(
            NetworkInterface.device_id == device.id,
            NetworkInterface.if_index == 1,
        )
    )
    assert row is not None
    row.link_speed_override_mbps = 1000
    row.last_polled_at = datetime.now(UTC).replace(microsecond=0) - timedelta(
        seconds=60
    )
    await session.commit()
    await save_interface_telemetry(
        session,
        device,
        {
            1: {
                "name": "ether1",
                "alias": "uplink",
                "admin": 1,
                "oper": 1,
                "speed": 0,
                "in_octets": 1_000_100,
                "out_octets": 240,
                "in_errors": 3,
                "out_errors": 0,
                "in_discards": 0,
                "out_discards": 1,
                "crc_errors": 4,
            }
        },
    )

    row = await session.scalar(
        select(NetworkInterface).where(
            NetworkInterface.device_id == device.id,
            NetworkInterface.if_index == 1,
        )
    )
    assert row is not None
    assert row.alias == "uplink"
    assert row.link_speed_mbps is None
    assert row.link_speed_override_mbps == 1000
    assert int(row.last_in_octets) == 1_000_100
    assert counter._value.get() - initial_total == 1_000_000
    assert crc_counter._value.get() - initial_crc_total == 3
    assert INTERFACE_IN_UTILIZATION_PERCENT.labels(*labels)._value.get() == pytest.approx(
        0.013333, rel=0.02
    )


async def test_routeros_operational_snapshots_are_upserted(session):
    site = await make_site(session, "RS")
    device = await make_device(session, site, "routeros-snapshot-test")
    await save_device_snapshots(
        session,
        device,
        {"dhcp_leases": [{"address": "192.0.2.10", "host-name": "client"}]},
    )
    await session.commit()
    await save_device_snapshots(
        session,
        device,
        {"dhcp_leases": [{"address": "192.0.2.11", "host-name": "updated"}]},
    )
    await session.commit()

    rows = await session.scalars(
        select(DeviceSnapshot).where(DeviceSnapshot.device_id == device.id)
    )
    snapshots = list(rows)
    assert len(snapshots) == 1
    assert snapshots[0].snapshot_type == "dhcp_leases"
    assert snapshots[0].payload == [
        {"address": "192.0.2.11", "host-name": "updated"}
    ]


async def test_neighbors_are_upserted_and_stale_rows_removed(session):
    from app.collectors.base import NeighborData

    site = await make_site(session, "NB")
    device = await make_device(session, site, "cisco-neighbor-test")
    await save_neighbors(
        session,
        device,
        [
            NeighborData(
                protocol="cdp",
                local_interface="Gi0/1",
                remote_device="sw2",
                remote_interface="Gi0/2",
                remote_platform="C9300",
                remote_address="192.0.2.2",
                capabilities="switch",
            ),
            NeighborData(
                protocol="lldp",
                local_interface="Gi0/2",
                remote_device="sw3",
            ),
        ],
    )
    await session.commit()

    await save_neighbors(
        session,
        device,
        [
            NeighborData(
                protocol="cdp",
                local_interface="Gi0/1",
                remote_device="sw2",
                remote_interface="Gi0/2",
                remote_platform="C9300X",
            )
        ],
    )
    await session.commit()

    rows = list(
        await session.scalars(
            select(DeviceNeighbor).where(DeviceNeighbor.device_id == device.id)
        )
    )
    assert len(rows) == 1
    assert rows[0].remote_device == "sw2"
    assert rows[0].remote_platform == "C9300X"
    assert rows[0].remote_address is None


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
    assert DEVICE_LATENCY_MS.labels(*labels)._value.get() == pytest.approx(12)
    assert PACKET_LOSS_PERCENT.labels(*labels)._value.get() == pytest.approx(
        25
    )
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
    assert PACKET_LOSS_PERCENT.labels(*labels)._value.get() == 100
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


async def test_configured_restconf_check_uses_cisco_probe(monkeypatch):
    from app import worker
    from app.collectors.cisco import restconf

    calls = []

    async def fake_probe(device):
        calls.append(device.name)
        return 0.02

    monkeypatch.setattr(restconf, "probe_restconf", fake_probe)
    monkeypatch.setattr(worker, "decrypt_secret", lambda _value: "unused")
    device = Device(
        site_id=1,
        name="cisco-restconf-check",
        mgmt_ip="192.0.2.6",
        check_type="restconf",
        credential_profile=CredentialProfile(
            name="cisco-restconf-profile",
            credential_type=CredentialType.CISCO_RESTCONF,
            username="monitor",
            secret_ciphertext="unused",
        ),
    )

    result = await configured_check(device)
    assert result.is_alive
    assert result.avg_rtt == 0.02
    assert calls == ["cisco-restconf-check"]


async def test_routeros_api_check_uses_https_and_profile_options(monkeypatch):
    from app import worker
    from app.collectors.mikrotik import collector as mikrotik

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

    monkeypatch.setattr(mikrotik.httpx, "AsyncClient", FakeClient)
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
