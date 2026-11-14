"""Run connectivity checks from the poller-worker container."""

import asyncio
import importlib
import os
import sys
from typing import Any

import httpx

SNMP_HOST = os.getenv("LAB_SNMP_HOST", "snmp-lab")
ROUTEROS_URL = os.getenv(
    "LAB_ROUTEROS_URL", "https://mikrotik-chr/rest/system/resource"
)


async def snmp_walk(auth: Any, label: str) -> int:
    hlapi: Any = importlib.import_module("pysnmp.hlapi.v3arch.asyncio")

    engine = hlapi.SnmpEngine()
    try:
        target = await hlapi.UdpTransportTarget.create(
            (SNMP_HOST, 161), timeout=2, retries=1
        )
        count = 0
        async for indication, error_status, _, var_binds in hlapi.walk_cmd(
            engine,
            auth,
            target,
            hlapi.ContextData(),
            hlapi.ObjectType(hlapi.ObjectIdentity("1.3.6.1.2.1.1")),
            lexicographicMode=False,
        ):
            if indication:
                raise OSError(f"{label} SNMP walk failed: {indication}")
            if error_status:
                raise OSError(f"{label} SNMP walk failed: {error_status}")
            count += len(var_binds)
        if count == 0:
            raise OSError(f"{label} SNMP walk returned no system objects")
        return count
    finally:
        engine.close_dispatcher()


async def run() -> None:
    hlapi: Any = importlib.import_module("pysnmp.hlapi.v3arch.asyncio")

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
        hlapi.UsmUserData(
            username,
            authKey=auth_passphrase,
            privKey=privacy_passphrase,
            authProtocol=hlapi.usmHMACSHAAuthProtocol,
            privProtocol=hlapi.usmAesCfb128Protocol,
        ),
        "SNMPv3 authPriv",
    )
    print(f"SNMPv3 authPriv walk: {v3_count} system objects")

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
