"""Syslog parsers for RFC 3164/5424, MikroTik RouterOS, and Cisco IOS."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

EVENT_LINK_UP = "link_up"
EVENT_LINK_DOWN = "link_down"
EVENT_INTERFACE_STATE = "interface_state"
EVENT_AUTH_SUCCESS = "auth_success"
EVENT_AUTH_FAILURE = "auth_failure"
EVENT_CONFIG_CHANGE = "config_change"
EVENT_BGP_CHANGE = "bgp_change"
EVENT_DHCP = "dhcp"
EVENT_PPP = "ppp"
EVENT_GENERIC = "generic"

ALWAYS_STORE = {
    EVENT_LINK_DOWN,
    EVENT_AUTH_FAILURE,
    EVENT_BGP_CHANGE,
    EVENT_CONFIG_CHANGE,
}

_PRI = re.compile(r"^<(?P<pri>\d{1,3})>")
_RFC5424 = re.compile(
    r"^(?P<version>\d)\s+"
    r"(?P<timestamp>\S+)\s+"
    r"(?P<hostname>\S+)\s+"
    r"(?P<app>\S+)\s+"
    r"(?P<procid>\S+)\s+"
    r"(?P<msgid>\S+)\s+"
    r"(?P<structured>(?:\[.*?\])|-)\s*"
    r"(?P<message>.*)$",
    re.DOTALL,
)
_RFC3164_TS = re.compile(
    r"^(?P<timestamp>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}):?\s*"
)
_CISCO = re.compile(
    r"%(?P<facility>[A-Z0-9_]+)-(?P<severity>\d)-(?P<mnemonic>[A-Z0-9_]+):\s*"
    r"(?P<message>.*)",
    re.DOTALL,
)
_ROUTEROS_TOPICS = re.compile(
    r"^(?P<topics>[a-z][a-z0-9_]*(?:,[a-z0-9_]+)*)\s+(?P<message>.*)$",
    re.DOTALL | re.IGNORECASE,
)
_ROUTEROS_HOST_TOPIC = re.compile(
    r"^(?P<hostname>[A-Za-z0-9_.-]+)\s+"
    r"(?P<topics>[a-z][a-z0-9_]*(?:,[a-z0-9_]+)+)\s+"
    r"(?P<message>.*)$",
    re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedSyslog:
    facility: int
    severity: int
    occurred_at: datetime
    hostname: str | None
    app_name: str | None
    event_type: str
    message: str
    raw: str


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _split_pri(raw: str) -> tuple[int, int, str]:
    match = _PRI.match(raw)
    if match is None:
        return 1, 6, raw
    pri = int(match.group("pri"))
    if pri > 191:
        return 1, 6, raw[match.end() :].lstrip()
    return pri >> 3, pri & 7, raw[match.end() :].lstrip()


def _parse_timestamp(value: str, now: datetime) -> datetime | None:
    text = value.strip()
    if not text or text == "-":
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
    if parsed is not None:
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    try:
        parsed = datetime.strptime(f"{now.year} {text}", "%Y %b %d %H:%M:%S").replace(
            tzinfo=UTC
        )
    except ValueError:
        return None
    if parsed > now + timedelta(days=1):
        parsed = parsed.replace(year=now.year - 1)
    return parsed


def _classify(app_name: str | None, message: str) -> str:
    lowered = f"{app_name or ''} {message}".lower()
    topics = (app_name or "").lower().split(",")
    topic = topics[0] if topics and topics[0] else ""

    if re.search(r"\b(link|line protocol)\b.*\b(down|deleted)\b", lowered):
        return EVENT_LINK_DOWN
    if re.search(r"\b(link|line protocol)\b.*\bup\b", lowered):
        return EVENT_LINK_UP
    if re.search(
        r"\b(login|log in|authentication|auth|password|ssh[a-z]*|sudo)\b",
        lowered,
    ):
        if re.search(r"\b(fail|failed|failure|denied|invalid|reject)", lowered):
            return EVENT_AUTH_FAILURE
        return EVENT_AUTH_SUCCESS
    if re.search(r"\b(config|configured|commit|changed configuration)\b", lowered):
        return EVENT_CONFIG_CHANGE
    if re.search(r"\bbgp\b", lowered):
        return EVENT_BGP_CHANGE
    if topic == "interface" or "interface," in lowered:
        return EVENT_INTERFACE_STATE
    if "dhcp" in lowered:
        return EVENT_DHCP
    if "ppp" in lowered:
        return EVENT_PPP
    return EVENT_GENERIC


def _cisco_name(match: re.Match[str]) -> str:
    return (
        f"%{match.group('facility').upper()}-{match.group('severity')}-"
        f"{match.group('mnemonic').upper()}"
    )


def _classify_cisco(match: re.Match[str], message: str) -> str:
    facility = match.group("facility").upper()
    mnemonic = match.group("mnemonic").upper()
    if facility in {"LINK", "LINEPROTO"}:
        lowered = message.lower()
        if "down" in lowered:
            return EVENT_LINK_DOWN
        if "up" in lowered:
            return EVENT_LINK_UP
        return EVENT_INTERFACE_STATE
    if facility == "SYS" and mnemonic == "CONFIG_I":
        return EVENT_CONFIG_CHANGE
    if facility == "BGP" and mnemonic == "ADJCHANGE":
        return EVENT_BGP_CHANGE
    return _classify(facility, message)


def _split_head(rest: str) -> tuple[str | None, str | None, str]:
    """Split ``hostname tag: message`` or ``tag: message``."""
    if ": " in rest:
        head, message = rest.split(": ", 1)
    elif rest.startswith("%") and ":" in rest:
        head, message = rest.split(":", 1)
        message = message.lstrip()
    else:
        return None, None, rest
    tokens = head.split()
    if not tokens:
        return None, None, message
    if len(tokens) == 1:
        return None, tokens[0], message
    return tokens[-2], tokens[-1], message


def parse_syslog(raw: str, now: datetime | None = None) -> ParsedSyslog:
    current = _now(now)
    facility, severity, rest = _split_pri(raw)

    rfc5424 = _RFC5424.match(rest)
    if rfc5424 is not None:
        timestamp = _parse_timestamp(rfc5424.group("timestamp"), current) or current
        app_name = None if rfc5424.group("app") == "-" else rfc5424.group("app")
        hostname = (
            None if rfc5424.group("hostname") == "-" else rfc5424.group("hostname")
        )
        message = rfc5424.group("message").strip() or rest
        cisco = _CISCO.search(message)
        event_type = (
            _classify_cisco(cisco, cisco.group("message"))
            if cisco is not None
            else _classify(app_name, message)
        )
        if cisco is not None:
            app_name = _cisco_name(cisco)
        return ParsedSyslog(
            facility=facility,
            severity=severity,
            occurred_at=timestamp,
            hostname=hostname,
            app_name=app_name,
            event_type=event_type,
            message=message,
            raw=raw,
        )

    timestamp = current
    ts_match = _RFC3164_TS.match(rest)
    if ts_match is not None:
        timestamp = _parse_timestamp(ts_match.group("timestamp"), current) or current
        rest = rest[ts_match.end() :]

    hostname, app_name, message = _split_head(rest)

    cisco = _CISCO.search(rest)
    if cisco is not None:
        hostname = None
        app_name = _cisco_name(cisco)
        message = cisco.group(0).strip()
        event_type = _classify_cisco(cisco, cisco.group("message"))
    else:
        host_topic = (
            _ROUTEROS_HOST_TOPIC.match(rest)
            if hostname is None and app_name is None
            else None
        )
        if host_topic is not None:
            hostname = host_topic.group("hostname")
            app_name = host_topic.group("topics")
            message = host_topic.group("message")
        else:
            topics = _ROUTEROS_TOPICS.match(message)
            if topics is not None and app_name is None:
                app_name = topics.group("topics")
                message = topics.group("message")
        event_type = _classify(app_name, message)

    return ParsedSyslog(
        facility=facility,
        severity=severity,
        occurred_at=timestamp,
        hostname=hostname,
        app_name=app_name,
        event_type=event_type,
        message=message.strip() or raw,
        raw=raw,
    )


def is_critical(parsed: ParsedSyslog, min_severity: int = 5) -> bool:
    """Keep notice-or-worse events plus security and topology changes."""
    return parsed.severity <= min_severity or parsed.event_type in ALWAYS_STORE
