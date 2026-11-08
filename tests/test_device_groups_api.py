"""API tests for /api/device-groups."""

from httpx import AsyncClient


async def make_group(client: AsyncClient, name: str = "Core", **overrides):
    data = {"name": name}
    data.update(overrides)
    return await client.post("/api/device-groups", json=data)


async def make_site(client: AsyncClient, code: str = "HQ"):
    response = await client.post(
        "/api/sites", json={"code": code, "name": f"Site {code}"}
    )
    assert response.status_code == 201
    return response.json()


async def make_device(client: AsyncClient, site_id: int, name: str, ip: str):
    response = await client.post(
        "/api/devices",
        json={"site_id": site_id, "name": name, "mgmt_ip": ip},
    )
    assert response.status_code == 201
    return response.json()


async def test_create_and_get_group(client: AsyncClient):
    response = await make_group(client, "Core routers", description="Backbone")
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["name"] == "Core routers"
    assert body["description"] == "Backbone"
    assert "created_at" in body and "updated_at" in body

    response = await client.get(f"/api/device-groups/{body['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == "Core routers"


async def test_duplicate_group_name_returns_409(client: AsyncClient):
    assert (await make_group(client)).status_code == 201
    response = await make_group(client, description="Other")
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "a device group with this name already exists"
    )


async def test_list_groups_paginates(client: AsyncClient):
    for i in range(3):
        assert (await make_group(client, f"group-{i}")).status_code == 201

    response = await client.get(
        "/api/device-groups", params={"limit": 2, "offset": 0}
    )
    page = response.json()
    assert page["total"] == 3
    assert [g["name"] for g in page["items"]] == ["group-0", "group-1"]

    response = await client.get(
        "/api/device-groups", params={"limit": 2, "offset": 2}
    )
    assert [g["name"] for g in response.json()["items"]] == ["group-2"]


async def test_missing_group_returns_404(client: AsyncClient):
    assert (await client.get("/api/device-groups/999")).status_code == 404
    assert (
        await client.patch("/api/device-groups/999", json={"name": "x"})
    ).status_code == 404
    assert (await client.delete("/api/device-groups/999")).status_code == 404


async def test_patch_updates_group(client: AsyncClient):
    created = (await make_group(client)).json()

    response = await client.patch(
        f"/api/device-groups/{created['id']}",
        json={"name": "Renamed", "description": "New description"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed"
    assert body["description"] == "New description"


async def test_patch_to_existing_name_returns_409(client: AsyncClient):
    first = (await make_group(client, "one")).json()
    assert (await make_group(client, "two")).status_code == 201

    response = await client.patch(
        f"/api/device-groups/{first['id']}", json={"name": "two"}
    )
    assert response.status_code == 409


async def test_patch_null_name_returns_422(client: AsyncClient):
    created = (await make_group(client)).json()

    response = await client.patch(
        f"/api/device-groups/{created['id']}", json={"name": None}
    )
    assert response.status_code == 422


async def test_delete_group_keeps_devices(client: AsyncClient):
    site = await make_site(client)
    group = (await make_group(client)).json()
    device = await make_device(client, site["id"], "rtr1", "10.0.0.1")
    assert (
        await client.post(
            f"/api/device-groups/{group['id']}/devices",
            json={"device_ids": [device["id"]]},
        )
    ).status_code == 204

    assert (await client.delete(f"/api/device-groups/{group['id']}")).status_code == 204
    assert (await client.get(f"/api/device-groups/{group['id']}")).status_code == 404

    response = await client.get(f"/api/devices/{device['id']}")
    assert response.status_code == 200
    assert response.json()["groups"] == []


async def test_add_list_and_remove_members(client: AsyncClient):
    site = await make_site(client)
    group = (await make_group(client)).json()
    first = await make_device(client, site["id"], "rtr1", "10.0.0.1")
    second = await make_device(client, site["id"], "rtr2", "10.0.0.2")

    response = await client.post(
        f"/api/device-groups/{group['id']}/devices",
        json={"device_ids": [first["id"], second["id"]]},
    )
    assert response.status_code == 204

    # Adding an existing member is idempotent.
    response = await client.post(
        f"/api/device-groups/{group['id']}/devices",
        json={"device_ids": [first["id"]]},
    )
    assert response.status_code == 204

    response = await client.get(f"/api/device-groups/{group['id']}/devices")
    page = response.json()
    assert page["total"] == 2
    assert [d["name"] for d in page["items"]] == ["rtr1", "rtr2"]

    response = await client.delete(
        f"/api/device-groups/{group['id']}/devices/{first['id']}"
    )
    assert response.status_code == 204

    response = await client.get(f"/api/device-groups/{group['id']}/devices")
    assert [d["name"] for d in response.json()["items"]] == ["rtr2"]

    response = await client.delete(
        f"/api/device-groups/{group['id']}/devices/{first['id']}"
    )
    assert response.status_code == 404


async def test_add_unknown_device_returns_422(client: AsyncClient):
    group = (await make_group(client)).json()

    response = await client.post(
        f"/api/device-groups/{group['id']}/devices",
        json={"device_ids": [999]},
    )
    assert response.status_code == 422
    assert "device(s) not found" in response.json()["detail"]


async def test_members_of_missing_group_returns_404(client: AsyncClient):
    response = await client.get("/api/device-groups/999/devices")
    assert response.status_code == 404

    response = await client.post(
        "/api/device-groups/999/devices", json={"device_ids": [1]}
    )
    assert response.status_code == 404
