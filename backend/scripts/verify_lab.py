"""Run connectivity checks from the poller-worker container."""

import asyncio
import importlib
import os
import sys
from typing import Any

import httpx
from icmplib.exceptions import ICMPLibError

SNMP_HOST = os.getenv("LAB_SNMP_HOST", "snmp-lab")
ROUTEROS_URL = os.getenv(
    "LAB_ROUTEROS_URL", "https://mikrotik-chr/rest/system/resource"
)
CISCO_HOST = os.getenv("LAB_CISCO_HOST", "").strip()
CISCO_REQUIRED = os.getenv("LAB_CISCO_REQUIRED", "false").lower() == "true"
SNMP_REQUIRED = os.getenv("LAB_SNMP_REQUIRED", "true").lower() == "true"
ROUTEROS_REQUIRED = (
    os.getenv("LAB_ROUTEROS_REQUIRED", "true").lower() == "true"
)

SYSTEM_OID = "1.3.6.1.2.1.1"
SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
# CISCO-PROCESS-MIB::cpmCPUTotal1minRev
CISCO_CPU_OID = "1.3.6.1.4.1.9.9.109.1.1.1.1.2"
CISCO_ENTERPRISE_PREFIX = "1.3.6.1.4.1.9."


async def snmp_walk(
    auth: Any,
    label: str,
    *,
    host: str = SNMP_HOST,
    base_oid: str = SYSTEM_OID,
) -> int:
    hlapi: Any = importlib.import_module("pysnmp.hlapi.v3arch.asyncio")

    engine = hlapi.SnmpEngine()
    try:
        target = await hlapi.UdpTransportTarget.create(
            (host, 161), timeout=2, retries=1
        )
        count = 0
        async for indication, error_status, _, var_binds in hlapi.walk_cmd(
            engine,
            auth,
            target,
            hlapi.ContextData(),
            hlapi.ObjectType(hlapi.ObjectIdentity(base_oid)),
            lexicographicMode=False,
        ):
            if indication:
                raise OSError(f"{label} SNMP walk failed: {indication}")
            if error_status:
                raise OSError(f"{label} SNMP walk failed: {error_status}")
            count += len(var_binds)
        if count == 0:
            raise OSError(f"{label} SNMP walk returned no objects")
        return count
    finally:
        engine.close_dispatcher()


async def snmp_get(auth: Any, label: str, *, host: str, oid: str) -> str:
    hlapi: Any = importlib.import_module("pysnmp.hlapi.v3arch.asyncio")

    engine = hlapi.SnmpEngine()
    try:
        target = await hlapi.UdpTransportTarget.create(
            (host, 161), timeout=2, retries=1
        )
        indication, error_status, _, var_binds = await hlapi.get_cmd(
            engine,
            auth,
            target,
            hlapi.ContextData(),
            hlapi.ObjectType(hlapi.ObjectIdentity(oid)),
        )
    finally:
        engine.close_dispatcher()
    if indication:
        raise OSError(f"{label} SNMP GET failed: {indication}")
    if error_status:
        raise OSError(f"{label} SNMP GET failed: {error_status}")
    if not var_binds:
        raise OSError(f"{label} SNMP GET returned no values")
    return str(var_binds[0][1])


def v3_auth(hlapi: Any, username: str, auth: str, privacy: str) -> Any:
    return hlapi.UsmUserData(
        username,
        authKey=auth,
        privKey=privacy,
        authProtocol=hlapi.usmHMACSHAAuthProtocol,
        privProtocol=hlapi.usmAesCfb128Protocol,
    )


async def verify_cisco(hlapi: Any, auth_passphrase: str, privacy: str) -> None:
    if not CISCO_HOST:
        message = "Cisco lab skipped: LAB_CISCO_HOST is not set"
        if CISCO_REQUIRED:
            raise OSError(message)
        print(message)
        return

    username = os.getenv("LAB_CISCO_SNMP_V3_USER") or os.getenv(
        "LAB_SNMP_V3_USER"
    )
    if not username:
        raise ValueError("LAB_CISCO_SNMP_V3_USER is required")
    if not auth_passphrase or not privacy:
        raise ValueError("Cisco SNMPv3 authPriv passphrases are required")
    auth = v3_auth(hlapi, username, auth_passphrase, privacy)

    object_id = await snmp_get(
        auth, "Cisco sysObjectID", host=CISCO_HOST, oid=SYS_OBJECT_ID
    )
    if not object_id.startswith(CISCO_ENTERPRISE_PREFIX):
        raise OSError(
            f"Cisco sysObjectID {object_id} is not under {CISCO_ENTERPRISE_PREFIX}"
        )
    print(f"Cisco sysObjectID: {object_id}")

    cpu_count = await snmp_walk(
        auth, "Cisco enterprise", host=CISCO_HOST, base_oid=CISCO_CPU_OID
    )
    print(f"Cisco enterprise OID walk: {cpu_count} CPU table objects")

    await verify_cisco_restconf()


async def verify_cisco_restconf() -> None:
    username = os.getenv("LAB_CISCO_RESTCONF_USER")
    password = os.getenv("LAB_CISCO_RESTCONF_PASSWORD")
    if not username or not password:
        print(
            "Cisco RESTCONF skipped: "
            "LAB_CISCO_RESTCONF_USER/PASSWORD is not set"
        )
        return

    verify_tls = os.getenv("LAB_CISCO_VERIFY_TLS", "false").lower() == "true"
    url = (
        f"https://{CISCO_HOST}/restconf/data/"
        "Cisco-IOS-XE-native:native/version"
    )
    async with httpx.AsyncClient(
        verify=verify_tls, timeout=10, auth=(username, password)
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
    version = None
    if isinstance(payload, dict):
        version = payload.get("Cisco-IOS-XE-native:version") or payload.get(
            "version"
        )
    if not isinstance(version, str) or not version:
        raise OSError("Cisco RESTCONF returned an unexpected version payload")
    print(f"Cisco RESTCONF: version={version}")


async def run() -> None:
    hlapi: Any = importlib.import_module("pysnmp.hlapi.v3arch.asyncio")

    await verify_snmp(hlapi)
    await verify_routeros()
    await verify_cisco(
        hlapi,
        auth_passphrase=os.environ.get("LAB_SNMP_V3_AUTH_PASSPHRASE", ""),
        privacy=os.environ.get("LAB_SNMP_V3_PRIV_PASSPHRASE", ""),
    )


async def verify_snmp(hlapi: Any) -> None:
    try:
        await _verify_snmp(hlapi)
    except (OSError, ValueError, ICMPLibError) as exc:
        if SNMP_REQUIRED:
            raise
        print(f"SNMP lab skipped: {exc}")


async def _verify_snmp(hlapi: Any) -> None:
    icmplib: Any = importlib.import_module("icmplib")
    ping = await icmplib.async_ping(SNMP_HOST, count=3, timeout=2)
    if not ping.is_alive:
        raise OSError(f"ICMP ping to {SNMP_HOST} failed")
    print(f"ICMP {SNMP_HOST}: up, avg={ping.avg_rtt:.2f}ms")

    community = os.getenv("LAB_SNMP_V2C_COMMUNITY")
    if not community:
        raise ValueError("LAB_SNMP_V2C_COMMUNITY is required")
    v2_count = await snmp_walk(
        hlapi.CommunityData(community, mpModel=1), "SNMPv2c"
    )
    print(f"SNMPv2c walk: {v2_count} system objects")

    username = os.getenv("LAB_SNMP_V3_USER")
    auth_passphrase = os.getenv("LAB_SNMP_V3_AUTH_PASSPHRASE")
    privacy_passphrase = os.getenv("LAB_SNMP_V3_PRIV_PASSPHRASE")
    if not username or not auth_passphrase or not privacy_passphrase:
        raise ValueError("SNMPv3 lab credentials are required")
    v3_count = await snmp_walk(
        v3_auth(hlapi, username, auth_passphrase, privacy_passphrase),
        "SNMPv3 authPriv",
    )
    print(f"SNMPv3 authPriv walk: {v3_count} system objects")


async def verify_routeros() -> None:
    try:
        await _verify_routeros()
    except (OSError, ValueError, httpx.HTTPError) as exc:
        if ROUTEROS_REQUIRED:
            raise
        print(f"RouterOS lab skipped: {exc}")


async def _verify_routeros() -> None:
    routeros_user = os.getenv("LAB_ROUTEROS_USER")
    routeros_password = os.getenv("LAB_ROUTEROS_PASSWORD")
    if not routeros_user or not routeros_password:
        raise ValueError("RouterOS lab credentials are required")
    verify_tls = os.getenv("LAB_ROUTEROS_VERIFY_TLS", "false").lower() == "true"
    async with httpx.AsyncClient(
        verify=verify_tls,
        timeout=10,
        auth=(routeros_user, routeros_password),
    ) as client:
        response = await client.get(ROUTEROS_URL)
        response.raise_for_status()
        resource = response.json()
    if not isinstance(resource, dict) or "version" not in resource:
        raise OSError("RouterOS REST returned an unexpected resource payload")
    print(f"RouterOS REST: version={resource['version']}")


def main() -> None:
    try:
        asyncio.run(run())
    except Exception as exc:
        print(f"Lab verification failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
