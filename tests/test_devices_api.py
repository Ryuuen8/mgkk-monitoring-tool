"""API tests for /api/devices. Needs the disposable PostgreSQL test database."""

from httpx import AsyncClient


async def make_site(client: AsyncClient, code: str = "HQ", name: str = "Headquarters"):
    response = await client.post("/api/sites", json={"code": code, "name": name})
    assert response.status_code == 201
    return response.json()


async def make_group(client: AsyncClient, name: str = "Core"):
    response = await client.post("/api/device-groups", json={"name": name})
    assert response.status_code == 201
    return response.json()


async def make_device(client: AsyncClient, site_id: int, **overrides):
    data = {"site_id": site_id, "name": "rtr1", "mgmt_ip": "10.0.0.1"}
    data.update(overrides)
    return await client.post("/api/devices", json=data)


async def test_create_device_returns_detail(client: AsyncClient):
    site = await make_site(client)
    group = await make_group(client, "Core routers")

    response = await make_device(
        client,
        site["id"],
        name="core-rtr-1",
        mgmt_ip="192.168.88.1",
        mac="AA-BB-CC-DD-EE-FF",
        vendor="MikroTik",
        device_type="router",
        tags={"role": "edge"},
        group_ids=[group["id"]],
    )
    assert response.status_code == 201

    body = response.json()
    assert body["id"] > 0
    assert body["name"] == "core-rtr-1"
    assert body["mgmt_ip"] == "192.168.88.1"
    assert body["mac"] == "aa:bb:cc:dd:ee:ff"
    assert body["vendor"] == "mikrotik"
    assert body["device_type"] == "router"
    assert body["tags"] == {"role": "edge"}
    assert body["site"]["code"] == "HQ"
    assert [g["name"] for g in body["groups"]] == ["Core routers"]
    assert body["parent"] is None


async def test_get_device_detail(client: AsyncClient):
    site = await make_site(client)
    created = (await make_device(client, site["id"])).json()

    response = await client.get(f"/api/devices/{created['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["site"]["id"] == site["id"]
    assert body["groups"] == []


async def test_get_missing_device_returns_404(client: AsyncClient):
    response = await client.get("/api/devices/999")
    assert response.status_code == 404
    assert response.json()["detail"] == "device not found"


async def test_list_devices_filters_and_paginates(client: AsyncClient):
    site_a = await make_site(client, "A", "Site A")
    site_b = await make_site(client, "B", "Site B")
    for i in range(3):
        assert (
            await make_device(
                client, site_a["id"], name=f"a{i}", mgmt_ip=f"10.0.0.{i + 1}"
            )
        ).status_code == 201
    assert (
        await make_device(client, site_b["id"], name="b0", mgmt_ip="10.0.1.1")
    ).status_code == 201

    response = await client.get(
        "/api/devices", params={"site_id": site_a["id"], "limit": 2}
    )
    page = response.json()
    assert page["total"] == 3
    assert [d["name"] for d in page["items"]] == ["a0", "a1"]

    response = await client.get("/api/devices", params={"site_id": site_b["id"]})
    assert [d["name"] for d in response.json()["items"]] == ["b0"]

    response = await client.get("/api/devices", params={"device_type": "router"})
    assert response.json()["total"] == 0


async def test_list_devices_filters_by_is_active(client: AsyncClient):
    site = await make_site(client)
    assert (await make_device(client, site["id"], name="on")).status_code == 201
    assert (
        await make_device(
            client, site["id"], name="off", mgmt_ip="10.0.0.2", is_active=False
        )
    ).status_code == 201

    response = await client.get("/api/devices", params={"is_active": "false"})
    assert [d["name"] for d in response.json()["items"]] == ["off"]


async def test_duplicate_device_name_returns_409(client: AsyncClient):
    site = await make_site(client)
    assert (await make_device(client, site["id"])).status_code == 201
    response = await make_device(client, site["id"], mgmt_ip="10.0.0.2")
    assert response.status_code == 409
    assert response.json()["detail"] == "a device with this name already exists"


async def test_create_device_with_missing_site_returns_422(client: AsyncClient):
    response = await make_device(client, 999)
    assert response.status_code == 422
    assert response.json()["detail"] == "site not found"


async def test_create_device_with_missing_group_returns_422(client: AsyncClient):
    site = await make_site(client)
    response = await make_device(client, site["id"], group_ids=[999])
    assert response.status_code == 422
    assert "device group(s) not found" in response.json()["detail"]


async def test_create_device_with_missing_parent_returns_422(client: AsyncClient):
    site = await make_site(client)
    response = await make_device(client, site["id"], parent_device_id=999)
    assert response.status_code == 422
    assert response.json()["detail"] == "parent device not found"


async def test_invalid_device_payload_returns_422(client: AsyncClient):
    site = await make_site(client)
    assert (
        await make_device(client, site["id"], mgmt_ip="999.1.1.1")
    ).status_code == 422


async def test_routeros_api_requires_mikrotik_collector(
    client: AsyncClient, monkeypatch
):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    site = await make_site(client)
    profile = await client.post(
        "/api/credential-profiles",
        json={
            "name": "RouterOS API",
            "credential_type": "routeros_api",
            "username": "monitor",
            "secret": "read-only-password",
        },
    )
    assert profile.status_code == 201
    response = await make_device(
        client,
        site["id"],
        check_type="routeros_api",
        collector="generic",
        credential_profile_id=profile.json()["id"],
    )
    assert response.status_code == 422
    assert "MikroTik collector" in response.json()["detail"]
    assert (
        await make_device(client, site["id"], poll_interval_seconds=1)
    ).status_code == 422


async def test_patch_updates_only_sent_fields(client: AsyncClient):
    site = await make_site(client)
    created = (await make_device(client, site["id"])).json()

    response = await client.patch(
        f"/api/devices/{created['id']}", json={"name": "renamed"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "renamed"
    assert body["mgmt_ip"] == "10.0.0.1"
    assert body["site"]["id"] == site["id"]


async def test_patch_replaces_groups(client: AsyncClient):
    site = await make_site(client)
    group_one = await make_group(client, "One")
    group_two = await make_group(client, "Two")
    created = (
        await make_device(client, site["id"], group_ids=[group_one["id"]])
    ).json()
    assert [g["name"] for g in created["groups"]] == ["One"]

    response = await client.patch(
        f"/api/devices/{created['id']}", json={"group_ids": [group_two["id"]]}
    )
    assert response.status_code == 200
    assert [g["name"] for g in response.json()["groups"]] == ["Two"]

    response = await client.patch(
        f"/api/devices/{created['id']}", json={"group_ids": []}
    )
    assert response.status_code == 200
    assert response.json()["groups"] == []


async def test_patch_device_cannot_be_its_own_parent(client: AsyncClient):
    site = await make_site(client)
    created = (await make_device(client, site["id"])).json()

    response = await client.patch(
        f"/api/devices/{created['id']}",
        json={"parent_device_id": created["id"]},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "device cannot be its own parent"


async def test_patch_null_required_field_returns_422(client: AsyncClient):
    site = await make_site(client)
    created = (await make_device(client, site["id"])).json()

    response = await client.patch(
        f"/api/devices/{created['id']}", json={"name": None}
    )
    assert response.status_code == 422
    assert "fields may not be null" in response.json()["detail"]


async def test_patch_missing_device_returns_404(client: AsyncClient):
    response = await client.patch("/api/devices/999", json={"name": "nope"})
    assert response.status_code == 404


async def test_delete_device_and_null_child_parent(client: AsyncClient):
    site = await make_site(client)
    parent = (await make_device(client, site["id"], name="parent")).json()
    child = (
        await make_device(
            client,
            site["id"],
            name="child",
            mgmt_ip="10.0.0.2",
            parent_device_id=parent["id"],
        )
    ).json()
    assert child["parent"]["id"] == parent["id"]

    response = await client.delete(f"/api/devices/{parent['id']}")
    assert response.status_code == 204
    assert (await client.get(f"/api/devices/{parent['id']}")).status_code == 404

    response = await client.get(f"/api/devices/{child['id']}")
    assert response.status_code == 200
    assert response.json()["parent"] is None

    assert (await client.delete("/api/devices/999")).status_code == 404
