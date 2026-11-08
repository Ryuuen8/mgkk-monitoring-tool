"""API tests for /api/sites. Needs the disposable PostgreSQL test database."""

from httpx import AsyncClient


async def create_site(client: AsyncClient, **overrides):
    data = {"code": "hq", "name": "Headquarters"}
    data.update(overrides)
    return await client.post("/api/sites", json=data)


async def test_create_and_get(client: AsyncClient):
    response = await create_site(client)
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["code"] == "hq"
    assert body["name"] == "Headquarters"
    assert body["timezone"] == "UTC"
    assert "created_at" in body and "updated_at" in body

    response = await client.get(f"/api/sites/{body['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == "Headquarters"


async def test_list_sites_paginates(client: AsyncClient):
    for i in range(3):
        assert (await create_site(client, code=f"site-{i}")).status_code == 201

    response = await client.get("/api/sites", params={"limit": 2, "offset": 0})
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 3
    assert page["limit"] == 2
    assert page["offset"] == 0
    assert [item["code"] for item in page["items"]] == ["site-0", "site-1"]

    response = await client.get("/api/sites", params={"limit": 2, "offset": 2})
    assert [item["code"] for item in response.json()["items"]] == ["site-2"]


async def test_list_rejects_bad_pagination(client: AsyncClient):
    assert (await client.get("/api/sites", params={"limit": 0})).status_code == 422
    assert (await client.get("/api/sites", params={"offset": -1})).status_code == 422


async def test_get_missing_site_returns_404(client: AsyncClient):
    response = await client.get("/api/sites/999")
    assert response.status_code == 404
    assert response.json()["detail"] == "site not found"


async def test_duplicate_code_returns_409(client: AsyncClient):
    assert (await create_site(client)).status_code == 201
    response = await create_site(client, name="Other")
    assert response.status_code == 409
    assert response.json()["detail"] == "a site with this code already exists"


async def test_patch_updates_only_sent_fields(client: AsyncClient):
    created = (await create_site(client)).json()

    response = await client.patch(
        f"/api/sites/{created['id']}", json={"name": "HQ Renamed"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "HQ Renamed"
    assert body["code"] == "hq"
    assert body["timezone"] == "UTC"


async def test_patch_to_existing_code_returns_409(client: AsyncClient):
    first = (await create_site(client, code="one")).json()
    assert (await create_site(client, code="two")).status_code == 201

    response = await client.patch(f"/api/sites/{first['id']}", json={"code": "two"})
    assert response.status_code == 409


async def test_patch_missing_site_returns_404(client: AsyncClient):
    response = await client.patch("/api/sites/999", json={"name": "nope"})
    assert response.status_code == 404


async def test_delete_site(client: AsyncClient):
    created = (await create_site(client)).json()

    response = await client.delete(f"/api/sites/{created['id']}")
    assert response.status_code == 204
    assert (await client.get(f"/api/sites/{created['id']}")).status_code == 404
    assert (await client.delete(f"/api/sites/{created['id']}")).status_code == 404


async def test_patch_null_required_field_returns_422(client: AsyncClient):
    created = (await create_site(client)).json()

    response = await client.patch(
        f"/api/sites/{created['id']}", json={"name": None}
    )
    assert response.status_code == 422


async def test_site_with_devices_cannot_be_deleted(client: AsyncClient):
    site = (await create_site(client)).json()
    device = await client.post(
        "/api/devices",
        json={"site_id": site["id"], "name": "rtr1", "mgmt_ip": "10.0.0.1"},
    )
    assert device.status_code == 201

    response = await client.delete(f"/api/sites/{site['id']}")
    assert response.status_code == 409
    assert "still has devices" in response.json()["detail"]
