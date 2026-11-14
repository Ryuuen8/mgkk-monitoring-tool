"""Lightweight device fingerprinting helpers.

This is intentionally small: it probes a handful of well-known ports and
suggests a device type from the result. It is not a full scanner and should
only be used against hosts you own or are authorised to probe.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass

COMMON_PORTS: tuple[int, ...] = (
    22, 23, 53, 80, 161, 443, 8291, 8080, 8443, 8728, 8729,
)


@dataclass(frozen=True)
class FingerprintResult:
    ip: str
    open_ports: list[int]
    suggested_device_type: str
    reason: str


def scan_ports(ip: str, ports: tuple[int, ...] = COMMON_PORTS, timeout: float = 1.0) -> list[int]:
    open_ports: list[int] = []
    for port in ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            if sock.connect_ex((ip, port)) == 0:
                open_ports.append(port)
        finally:
            sock.close()
    return open_ports


def suggest_device_type(open_ports: list[int]) -> tuple[str, str]:
    port_set = set(open_ports)
    if port_set & {8728, 8729}:
        return "router", "MikroTik RouterOS API port detected"
    if 161 in port_set:
        return "router", "SNMP agent detected"
    if port_set & {22, 23} and port_set & {80, 443, 8080, 8443}:
        return "server", "SSH/Telnet plus HTTP detected"
    if port_set & {80, 443, 8080, 8443}:
        return "access_point", "HTTP/HTTPS service detected"
    if port_set & {22, 23}:
        return "server", "SSH/Telnet detected"
    return "other", "no recognised service ports detected"


def fingerprint(ip: str, timeout: float = 1.0) -> FingerprintResult:
    open_ports = scan_ports(ip, timeout=timeout)
    suggested, reason = suggest_device_type(open_ports)
    return FingerprintResult(
        ip=ip,
        open_ports=open_ports,
        suggested_device_type=suggested,
        reason=reason,
    )