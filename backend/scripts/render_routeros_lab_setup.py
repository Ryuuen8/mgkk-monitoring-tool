"""Render a RouterOS read-only lab configuration from .env.lab values."""

import ipaddress
import os
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / ".lab" / "routeros-readonly-setup.rsc"
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
SAFE_SECRET_RE = re.compile(r"^[A-Za-z0-9_.@+-]{12,128}$")


def required(name: str, pattern: re.Pattern[str]) -> str:
    value = os.getenv(name, "")
    if not pattern.fullmatch(value):
        raise ValueError(f"{name} is missing or has an invalid format")
    return value


def main() -> None:
    load_dotenv(ROOT / ".env.lab")
    username = required("LAB_ROUTEROS_USER", USERNAME_RE)
    password = required("LAB_ROUTEROS_PASSWORD", SAFE_SECRET_RE)
    community = required("LAB_SNMP_V2C_COMMUNITY", USERNAME_RE)
    subnet = ipaddress.ip_network(
        os.getenv("LAB_POLLER_SUBNET", "172.30.50.0/24"), strict=True
    )
    if subnet.version != 4:
        raise ValueError("the lab poller subnet must be IPv4")

    commands = f"""\
/certificate add name=mgkk-lab-www-ssl common-name=mgkk-lab key-usage=tls-server
/certificate sign mgkk-lab-www-ssl
/ip service set [find name=www-ssl] disabled=no certificate=mgkk-lab-www-ssl address={subnet}
/user add name={username} group=read address={subnet} password="{password}"
/snmp set enabled=yes
/snmp community remove [find name=public]
/snmp community add name={community} addresses={subnet} read-access=yes write-access=no
"""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(commands, encoding="utf-8")
    print(f"RouterOS read-only lab setup written to {OUTPUT}")
    print("Apply this file in the CHR terminal; keep it private and delete it afterward.")


if __name__ == "__main__":
    main()
