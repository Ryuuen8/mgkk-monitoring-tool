from uuid import UUID

import pytest
from app.models import Device, DeviceNeighbor, NetworkInterface
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import select


async def create_site(client: AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/sites",
        json={"code": "V1", "name": "Version one site"},
    )
    assert response.status_code == 201
    return response.json()


async def create_device(
    client: AsyncClient, site_id: int, **overrides: object
) -> dict:
    payload: dict[str, object] = {
        "site_id": site_id,
        "name": "v1-router",
        "ip_address": "192.0.2.10",
        "collector": "generic_snmp",
    }
    payload.update(overrides)
    response = await client.post("/api/v1/devices", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_v1_site_group_and_device_crud(client: AsyncClient):
    site = await create_site(client)
    group_response = await client.post(
        "/api/v1/groups", json={"name": "Core", "description": "Core devices"}
    )
    assert group_response.status_code == 201
    group_id = group_response.json()["id"]

    parent = await create_device(
        client,
        site["id"],
        name="parent",
        collector="mikrotik",
        vendor="MikroTik",
    )
    child = await create_device(
        client,
        site["id"],
        name="child",
        parent_device_id=parent["id"],
    )

    assert UUID(parent["id"])
    assert parent["collector"] == "mikrotik"
    assert child["parent_device_id"] == parent["id"]

    listed = await client.get(
        "/api/v1/devices",
        params={"collector": "mikrotik", "site_id": site["id"]},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == parent["id"]

    updated = await client.patch(
        f"/api/v1/devices/{child['id']}",
        json={"ip_address": "192.0.2.11"},
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == child["id"]
    assert updated.json()["ip_address"] == "192.0.2.11"

    assert (await client.get(f"/api/v1/groups/{group_id}")).status_code == 200
    assert (await client.delete(f"/api/v1/groups/{group_id}")).status_code == 204


async def test_v1_mac_is_unique_while_ip_remains_mutable(client: AsyncClient):
    site = await create_site(client)
    device = await create_device(
        client,
        site["id"],
        mac_address="AA-BB-CC-DD-EE-FF",
    )

    changed = await client.patch(
        f"/api/v1/devices/{device['id']}",
        json={"ip_address": "192.0.2.20"},
    )
    assert changed.status_code == 200
    assert changed.json()["id"] == device["id"]
    assert changed.json()["ip_address"] == "192.0.2.20"
    assert changed.json()["mac_address"] == "aa:bb:cc:dd:ee:ff"

    duplicate = await client.post(
        "/api/v1/devices",
        json={
            "site_id": site["id"],
            "name": "duplicate-mac",
            "ip_address": "192.0.2.21",
            "mac_address": "aa:bb:cc:dd:ee:ff",
        },
    )
    assert duplicate.status_code == 409


async def test_v1_device_filters_and_pagination(client: AsyncClient):
    site = await create_site(client)
    await create_device(client, site["id"], name="mikrotik", collector="mikrotik")
    await create_device(client, site["id"], name="generic")

    response = await client.get(
        "/api/v1/devices",
        params={"site_id": site["id"], "collector": "generic_snmp", "limit": 1},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["collector"] == "generic_snmp"


async def test_v1_device_metrics_converts_units(client: AsyncClient, monkeypatch):
    site = await create_site(client)
    device = await create_device(client, site["id"])
    calls: list[str] = []

    async def fake_query_range(
        expression: str,
        *,
        start,
        end,
        step_seconds: int,
    ) -> list[dict]:
        calls.append(expression)
        value = "0.012" if "ping_latency_seconds" in expression else "25"
        return [{"values": [[1000, value]]}]

    monkeypatch.setattr(
        "app.api.routes.v1.prometheus.query_range", fake_query_range
    )
    response = await client.get(f"/api/v1/devices/{device['id']}/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["latency"][0]["value"] == pytest.approx(12)
    assert body["packet_loss_percent"][0]["value"] == pytest.approx(25)
    assert len(calls) == 2


async def test_v1_interface_list_override_and_metrics(
    client: AsyncClient, session, monkeypatch
):
    site = await create_site(client)
    device_payload = await create_device(
        client, site["id"], device_type="switch"
    )
    device = await session.scalar(
        select(Device).where(Device.public_id == device_payload["id"])
    )
    assert device is not None
    interface = NetworkInterface(
        device_id=device.id,
        if_index=2,
        name="eth0",
        alias="uplink",
        admin_status=1,
        oper_status=1,
        link_speed_mbps=0,
    )
    session.add(interface)
    await session.commit()

    listed = await client.get(f"/api/v1/devices/{device_payload['id']}/interfaces")
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "eth0"
    interface_id = listed.json()[0]["id"]

    updated = await client.patch(
        f"/api/v1/devices/{device_payload['id']}/interfaces/{interface_id}",
        json={"link_speed_override_mbps": 2500},
    )
    assert updated.status_code == 200
    assert updated.json()["link_speed_override_mbps"] == 2500

    expressions: list[str] = []

    async def fake_query_range(expression: str, *, start, end, step_seconds):
        expressions.append(expression)
        return [{"values": [[1000, "0.5"]]}]

    monkeypatch.setattr(
        "app.api.routes.v1.prometheus.query_range", fake_query_range
    )
    metrics = await client.get(
        f"/api/v1/devices/{device_payload['id']}/interfaces/{interface_id}/metrics",
        params={"range_hours": 168, "step_seconds": 1800},
    )
    assert metrics.status_code == 200
    body = metrics.json()
    assert body["range_seconds"] == 168 * 3600
    assert body["in_bits_per_second"][0]["value"] == 0.5
    assert body["out_utilization_percent"][0]["value"] == 0.5
    assert len(expressions) == 11
    assert all('device="v1-router"' in expression for expression in expressions)
    assert all('interface="eth0"' in expression for expression in expressions)

    invalid_range = await client.get(
        f"/api/v1/devices/{device_payload['id']}/interfaces/{interface_id}/metrics",
        params={"range_hours": 48},
    )
    assert invalid_range.status_code == 422

    async def fake_device_query_range(
        expression: str, *, start, end, step_seconds
    ):
        return [
            {
                "metric": {"interface": "eth0"},
                "values": [[1000, "2.5"]],
            }
        ]

    monkeypatch.setattr(
        "app.api.routes.v1.prometheus.query_range", fake_device_query_range
    )
    all_metrics = await client.get(
        f"/api/v1/devices/{device_payload['id']}/interfaces/metrics",
        params={"range_hours": 24, "step_seconds": 300},
    )
    assert all_metrics.status_code == 200
    assert len(all_metrics.json()) == 1
    assert all_metrics.json()[0]["interface_id"] == interface_id
    assert all_metrics.json()[0]["in_bits_per_second"] == [
        {"t": 1000.0, "value": 2.5}
    ]


async def test_v1_rejects_missing_parent_and_self_parent(client: AsyncClient):
    site = await create_site(client)
    missing_parent = await client.post(
        "/api/v1/devices",
        json={
            "site_id": site["id"],
            "name": "missing-parent",
            "ip_address": "192.0.2.30",
            "parent_device_id": "00000000-0000-0000-0000-000000000001",
        },
    )
    assert missing_parent.status_code == 422

    device = await create_device(client, site["id"])
    self_parent = await client.patch(
        f"/api/v1/devices/{device['id']}",
        json={"parent_device_id": device["id"]},
    )
    assert self_parent.status_code == 422


async def test_v1_cisco_collector_filter_and_restconf_validation(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    site = await create_site(client)
    device = await create_device(
        client, site["id"], name="cisco-edge", collector="cisco"
    )

    listed = await client.get(
        "/api/v1/devices", params={"collector": "cisco"}
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [device["id"]]

    invalid = await client.patch(
        f"/api/v1/devices/{device['id']}",
        json={"check_type": "restconf", "credential_profile_id": None},
    )
    assert invalid.status_code == 422

    profile = await client.post(
        "/api/credential-profiles",
        json={
            "name": "Cisco RESTCONF",
            "credential_type": "cisco_restconf",
            "username": "monitor",
            "secret": "restconf-password",
        },
    )
    assert profile.status_code == 201

    valid = await client.patch(
        f"/api/v1/devices/{device['id']}",
        json={
            "check_type": "restconf",
            "credential_profile_id": profile.json()["id"],
        },
    )
    assert valid.status_code == 200
    assert valid.json()["check_type"] == "restconf"

    mismatched = await client.patch(
        f"/api/v1/devices/{device['id']}",
        json={"collector": "mikrotik"},
    )
    assert mismatched.status_code == 422

    bad_collector = await client.get(
        "/api/v1/devices", params={"collector": "junos"}
    )
    assert bad_collector.status_code == 422


async def test_v1_device_neighbors_endpoint(client: AsyncClient, session):
    site = await create_site(client)
    payload = await create_device(
        client, site["id"], name="cisco-switch", collector="cisco"
    )
    device = await session.scalar(
        select(Device).where(Device.public_id == payload["id"])
    )
    assert device is not None
    session.add(
        DeviceNeighbor(
            device_id=device.id,
            protocol="cdp",
            local_interface="GigabitEthernet0/1",
            remote_device="core-sw",
            remote_interface="GigabitEthernet0/24",
            remote_platform="C9300",
            remote_address="192.0.2.2",
            capabilities="switch",
        )
    )
    await session.commit()

    response = await client.get(f"/api/v1/devices/{payload['id']}/neighbors")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["protocol"] == "cdp"
    assert body[0]["local_interface"] == "GigabitEthernet0/1"
    assert body[0]["remote_device"] == "core-sw"

    missing = await client.get(
        "/api/v1/devices/00000000-0000-0000-0000-000000000001/neighbors"
    )
    assert missing.status_code == 404
