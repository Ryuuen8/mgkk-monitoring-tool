"""Syslog parsing, filtering, framing, and persistence."""

from datetime import UTC, datetime

import pytest
from app.models import Device, Site, SyslogEvent
from app.syslog import receiver
from app.syslog.parsers import (
    EVENT_AUTH_FAILURE,
    EVENT_CONFIG_CHANGE,
    EVENT_GENERIC,
    EVENT_INTERFACE_STATE,
    EVENT_LINK_DOWN,
    is_critical,
    parse_syslog,
)
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

NOW = datetime(2026, 11, 14, 10, 30, tzinfo=UTC)


def test_cisco_link_down_uses_priority_and_mnemonic():
    parsed = parse_syslog(
        "<189>1 2026-11-14T10:29:58Z core-rtr1 IOS 4321 - - "
        "%LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to down",
        now=NOW,
    )

    assert parsed.facility == 23
    assert parsed.severity == 5
    assert parsed.hostname == "core-rtr1"
    assert parsed.app_name == "%LINK-3-UPDOWN"
    assert parsed.event_type == EVENT_LINK_DOWN
    assert parsed.occurred_at == datetime(2026, 11, 14, 10, 29, 58, tzinfo=UTC)
    assert "changed state to down" in parsed.message


def test_routeros_interface_topic_is_parsed():
    parsed = parse_syslog(
        "<30>Nov 14 10:29:50 mikrotik1 interface,info ether1 link down",
        now=NOW,
    )

    assert parsed.facility == 3
    assert parsed.severity == 6
    assert parsed.hostname == "mikrotik1"
    assert parsed.app_name == "interface,info"
    assert parsed.event_type == EVENT_LINK_DOWN
    assert parsed.occurred_at == datetime(2026, 11, 14, 10, 29, 50, tzinfo=UTC)


def test_rfc3164_cisco_config_change_is_detected():
    parsed = parse_syslog(
        "<189>Nov 14 10:29:40 10.0.0.1 136: Nov 14 10:29:40.123: "
        "%SYS-5-CONFIG_I: Configured from console by admin on vty0 "
        "(10.0.0.5)",
        now=NOW,
    )

    assert parsed.app_name == "%SYS-5-CONFIG_I"
    assert parsed.event_type == EVENT_CONFIG_CHANGE
    assert parsed.occurred_at == datetime(2026, 11, 14, 10, 29, 40, tzinfo=UTC)


def test_auth_failure_and_generic_classification():
    failed = parse_syslog(
        "<38>Nov 14 10:29:30 srv1 sshd[811]: Failed password for invalid "
        "user admin from 203.0.113.5 port 5555 ssh2",
        now=NOW,
    )
    assert failed.event_type == EVENT_AUTH_FAILURE
    assert is_critical(failed) is True

    routine = parse_syslog(
        "<30>Nov 14 10:29:20 mikrotik1 system,info router rebooted",
        now=NOW,
    )
    assert routine.event_type == EVENT_GENERIC
    assert is_critical(routine) is False
    assert is_critical(routine, min_severity=6) is True


def test_interface_state_without_link_change():
    parsed = parse_syslog(
        "<30>Nov 14 10:29:10 mikrotik1 interface,info ether2 running",
        now=NOW,
    )
    assert parsed.event_type == EVENT_INTERFACE_STATE


@pytest.mark.parametrize(
    ("buffer", "expected_frame", "expected_rest"),
    [
        (b"one\ntwo\n", b"one", b"two\n"),
        (b"one\r\ntwo", b"one", b"two"),
        (b"11 hello worldrest", b"hello world", b"rest"),
        (b"partial", None, b"partial"),
        (b"10 short", None, b"10 short"),
        (b"", None, b""),
    ],
)
def test_next_frame_supports_newline_and_octet_counting(
    buffer: bytes, expected_frame: bytes | None, expected_rest: bytes
):
    frame, rest = receiver._next_frame(buffer)
    assert frame == expected_frame
    assert rest == expected_rest


async def test_process_message_matches_device_and_persists(
    session, monkeypatch: pytest.MonkeyPatch
):
    published: list[tuple[str, dict]] = []

    async def fake_publish(event_type: str, payload: dict) -> None:
        published.append((event_type, payload))

    monkeypatch.setattr(receiver.events, "publish_event", fake_publish)

    site = Site(code="HQ", name="Headquarters")
    session.add(site)
    await session.flush()
    device = Device(
        site_id=site.id,
        site=site,
        name="mikrotik1",
        mgmt_ip="192.0.2.55",
        poll_interval_seconds=60,
    )
    session.add(device)
    await session.commit()

    maker = async_sessionmaker(session.bind, expire_on_commit=False)
    stored = await receiver.process_message(
        "<30>Nov 14 10:29:00 mikrotik1 interface,info ether1 link down",
        "192.0.2.55",
        session_factory=maker,
        now=NOW,
    )
    assert stored is True

    row = await session.scalar(select(SyslogEvent))
    assert row is not None
    assert row.device_id == device.id
    assert row.event_type == EVENT_LINK_DOWN
    assert str(row.source_ip) == "192.0.2.55"

    assert published[0][0] == "syslog_event"
    assert published[0][1]["device_id"] == str(device.public_id)
    assert published[0][1]["site"] == "HQ"

    ignored = await receiver.process_message(
        "<30>Nov 14 10:29:00 mikrotik1 system,info daily task finished",
        "192.0.2.55",
        session_factory=maker,
        now=NOW,
    )
    assert ignored is False
    assert len(published) == 1


async def test_syslog_api_filters(
    client: AsyncClient, session, monkeypatch: pytest.MonkeyPatch
):
    async def fake_publish(_event_type: str, _payload: dict) -> None:
        return None

    monkeypatch.setattr(receiver.events, "publish_event", fake_publish)

    site = Site(code="DC", name="Data center")
    session.add(site)
    await session.flush()
    device = Device(
        site_id=site.id,
        site=site,
        name="core-rtr1",
        mgmt_ip="192.0.2.60",
        poll_interval_seconds=60,
    )
    session.add(device)
    await session.commit()

    maker = async_sessionmaker(session.bind, expire_on_commit=False)
    await receiver.process_message(
        "<189>1 2026-11-14T10:29:00Z core-rtr1 IOS - - - "
        "%LINEPROTO-5-UPDOWN: Line protocol on Interface Gi0/1, changed state to down",
        "192.0.2.60",
        session_factory=maker,
        now=NOW,
    )
    await receiver.process_message(
        "<30>Nov 14 10:29:10 mikrotik9 interface,info ether1 link down",
        "192.0.2.99",
        session_factory=maker,
        now=NOW,
    )

    all_events = await client.get("/api/v1/syslog")
    assert all_events.status_code == 200
    assert all_events.json()["total"] == 2

    link_down = await client.get("/api/v1/syslog", params={"event_type": "link_down"})
    assert link_down.json()["total"] == 2

    by_device = await client.get(
        "/api/v1/syslog", params={"device_id": str(device.public_id)}
    )
    assert by_device.status_code == 200
    assert by_device.json()["total"] == 1
    assert by_device.json()["items"][0]["event_type"] == "link_down"
