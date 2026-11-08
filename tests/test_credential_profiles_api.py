"""API tests for encrypted credential profiles and device check selection."""

from app.models import CredentialProfile
from app.services.credentials import decrypt_secret
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import select


async def make_site(client: AsyncClient) -> dict:
    response = await client.post("/api/sites", json={"code": "LAB", "name": "Lab"})
    assert response.status_code == 201
    return response.json()


async def test_profile_secret_is_encrypted_and_never_returned(
    client: AsyncClient, session, monkeypatch
):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", key)

    response = await client.post(
        "/api/credential-profiles",
        json={
            "name": "Lab RouterOS",
            "credential_type": "routeros_api",
            "username": "monitor",
            "secret": "read-only-password",
        },
    )
    assert response.status_code == 201
    profile = response.json()
    assert profile["port"] == 443
    assert profile["secret_configured"] is True
    assert "secret" not in profile
    assert "secret_ciphertext" not in profile
    stored = await session.scalar(
        select(CredentialProfile).where(CredentialProfile.id == profile["id"])
    )
    assert stored is not None
    assert stored.secret_ciphertext != "read-only-password"
    assert decrypt_secret(stored.secret_ciphertext) == "read-only-password"

    listed = await client.get("/api/credential-profiles")
    assert listed.status_code == 200
    assert listed.json() == [profile]


async def test_create_profile_requires_encryption_key(client: AsyncClient, monkeypatch):
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    response = await client.post(
        "/api/credential-profiles",
        json={
            "name": "Lab SNMP",
            "credential_type": "snmp_v2c",
            "secret": "readonly-community",
        },
    )
    assert response.status_code == 503
    assert "CREDENTIAL_ENCRYPTION_KEY" in response.json()["detail"]


async def test_device_check_requires_matching_profile(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    site = await make_site(client)
    snmp_profile = await client.post(
        "/api/credential-profiles",
        json={
            "name": "Lab SNMP",
            "credential_type": "snmp_v2c",
            "secret": "readonly-community",
        },
    )
    assert snmp_profile.status_code == 201

    missing_profile = await client.post(
        "/api/devices",
        json={
            "site_id": site["id"],
            "name": "router-no-profile",
            "mgmt_ip": "192.168.88.1",
            "check_type": "snmp",
        },
    )
    assert missing_profile.status_code == 422
    assert "requires a credential profile" in missing_profile.json()["detail"]

    mismatch = await client.post(
        "/api/devices",
        json={
            "site_id": site["id"],
            "name": "router-wrong-profile",
            "mgmt_ip": "192.168.88.2",
            "check_type": "routeros_api",
            "collector": "mikrotik",
            "credential_profile_id": snmp_profile.json()["id"],
        },
    )
    assert mismatch.status_code == 422
    assert "does not match" in mismatch.json()["detail"]

    created = await client.post(
        "/api/devices",
        json={
            "site_id": site["id"],
            "name": "router-snmp",
            "mgmt_ip": "192.168.88.3",
            "vendor": "MikroTik",
            "check_type": "snmp",
            "credential_profile_id": snmp_profile.json()["id"],
        },
    )
    assert created.status_code == 201
    assert created.json()["vendor"] == "mikrotik"
    assert created.json()["check_type"] == "snmp"
    assert created.json()["credential_profile"]["name"] == "Lab SNMP"

    blocked_delete = await client.delete(
        f"/api/credential-profiles/{snmp_profile.json()['id']}"
    )
    assert blocked_delete.status_code == 409

    updated = await client.patch(
        f"/api/devices/{created.json()['id']}",
        json={"check_type": "ping_only", "credential_profile_id": None},
    )
    assert updated.status_code == 200
    deleted = await client.delete(
        f"/api/credential-profiles/{snmp_profile.json()['id']}"
    )
    assert deleted.status_code == 204


async def test_snmp_v3_profile_encrypts_auth_and_privacy_secrets(
    client: AsyncClient, session, monkeypatch
):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    response = await client.post(
        "/api/credential-profiles",
        json={
            "name": "SNMPv3 router",
            "credential_type": "snmp_v3",
            "username": "monitor",
            "secret": "auth-passphrase",
            "auth_protocol": "sha256",
            "privacy_protocol": "aes128",
            "privacy_secret": "privacy-passphrase",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["port"] == 161
    assert data["auth_protocol"] == "sha256"
    assert data["privacy_protocol"] == "aes128"
    assert data["privacy_secret_configured"] is True
    assert "secret" not in data
    assert "privacy_secret" not in data

    profile = await session.scalar(
        select(CredentialProfile).where(CredentialProfile.id == data["id"])
    )
    assert profile is not None
    assert decrypt_secret(profile.secret_ciphertext) == "auth-passphrase"
    assert profile.privacy_secret_ciphertext is not None
    assert decrypt_secret(profile.privacy_secret_ciphertext) == "privacy-passphrase"
    site = await make_site(client)
    device = await client.post(
        "/api/devices",
        json={
            "site_id": site["id"],
            "name": "snmpv3-device",
            "mgmt_ip": "192.0.2.25",
            "check_type": "snmp",
            "credential_profile_id": data["id"],
        },
    )
    assert device.status_code == 201


async def test_snmp_v3_profile_requires_privacy_secret_for_aes128(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    response = await client.post(
        "/api/credential-profiles",
        json={
            "name": "Invalid SNMPv3",
            "credential_type": "snmp_v3",
            "username": "monitor",
            "secret": "auth-passphrase",
            "auth_protocol": "sha",
            "privacy_protocol": "aes128",
        },
    )
    assert response.status_code == 422


async def test_profile_update_can_disable_snmp_v3_privacy(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    created = await client.post(
        "/api/credential-profiles",
        json={
            "name": "SNMPv3 privacy update",
            "credential_type": "snmp_v3",
            "username": "monitor",
            "secret": "auth-passphrase",
            "auth_protocol": "sha",
            "privacy_protocol": "aes128",
            "privacy_secret": "privacy-passphrase",
        },
    )
    assert created.status_code == 201

    updated = await client.patch(
        f"/api/credential-profiles/{created.json()['id']}",
        json={
            "privacy_protocol": "none",
            "privacy_secret": None,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["privacy_protocol"] == "none"
    assert updated.json()["privacy_secret_configured"] is False
