import hashlib
from types import SimpleNamespace

import httpx
from app.collectors import CollectionResult, get_collector
from app.collectors.generic import GenericCollector
from app.collectors.mikrotik import (
    MikroTikCollector,
    _BinaryApi,
    _collect_rest,
    _health_number,
    _interface_rows,
    _uptime_seconds,
    _wireless_summary,
    probe_routeros_api,
)
from app.models import CollectorType, DeviceCheckType
from app.services.credentials import encrypt_secret
from cryptography.fernet import Fernet


def test_registry_resolves_persisted_collector_types():
    assert isinstance(get_collector(CollectorType.GENERIC), GenericCollector)
    assert isinstance(get_collector(CollectorType.MIKROTIK), MikroTikCollector)


def test_mikrotik_interface_records_use_shared_telemetry_shape():
    interfaces = _interface_rows(
        [
            {
                "name": "ether1",
                "comment": "uplink",
                "disabled": "false",
                "running": "true",
                "speed": "1Gbps",
                "rx-byte": "123456",
                "tx-byte": "654321",
                "rx-error": "3",
                "tx-error": "4",
                "rx-drop": "5",
                "tx-drop": "6",
                "mac-address": "00:11:22:33:44:55",
                "host-name": "client-device",
            }
        ]
    )

    assert interfaces == {
        1: {
            "name": "ether1",
            "alias": "uplink",
            "admin": 1,
            "oper": 1,
            "speed": 1000,
            "in_octets": 123456,
            "out_octets": 654321,
            "in_errors": 3,
            "out_errors": 4,
            "in_discards": 5,
            "out_discards": 6,
        }
    }


def test_mikrotik_summary_parsers_do_not_retain_client_identifiers():
    assert _uptime_seconds("2w3d4h5m6s") == 1_483_506
    assert _health_number(
        [{"name": "voltage", "value": "24.2V"}], "voltage"
    ) == 24.2
    assert _wireless_summary(
        [
            {
                "interface": "wlan1",
                "signal-strength": "-60dBm",
                "mac-address": "00:11:22:33:44:55",
                "host-name": "client-a",
            },
            {"interface": "wlan1", "signal-strength": "-66dBm"},
            {"interface": "wlan1", "signal-strength": "unknown"},
        ]
    ) == {"wlan1": (3, -63)}


def test_binary_api_length_prefix_boundaries():
    assert _BinaryApi._encode_length(127) == b"\x7f"
    assert _BinaryApi._encode_length(128) == b"\x80\x80"
    assert _BinaryApi._encode_length(16384) == b"\xc0\x40\x00"


async def test_mikrotik_snmp_uses_shared_generic_system_interface_poll(monkeypatch):
    from app import worker

    device = SimpleNamespace(check_type=DeviceCheckType.SNMP)
    interfaces = {1: {"name": "ether1", "in_octets": 100}}
    calls = []

    async def shared_poll(passed_device):
        calls.append(passed_device)
        return interfaces

    monkeypatch.setattr(worker, "poll_snmp_telemetry", shared_poll)
    result = await MikroTikCollector().collect(device)

    assert calls == [device]
    assert result == CollectionResult(interfaces=interfaces)


async def test_routeros_rest_persists_aggregated_telemetry_only(monkeypatch):
    from app.collectors import mikrotik
    from app.worker import MIKROTIK_WIRELESS_CLIENTS
    from prometheus_client import generate_latest

    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    payloads = {
        "system/resource": {
            "board-name": "CHR",
            "version": "7.16",
            "uptime": "1d2h",
            "cpu-load": "12",
            "total-memory": "1024",
            "free-memory": "512",
            "total-hdd-space": "4096",
            "free-hdd-space": "2048",
        },
        "system/identity": {"name": "lab-router"},
        "system/health": [
            {"name": "temperature", "value": "45C"},
            {"name": "voltage", "value": "24.2V"},
        ],
        "interface": [
            {
                "name": "ether1",
                "running": "true",
                "disabled": "false",
                "speed": "1Gbps",
                "rx-byte": "4096",
                "tx-byte": "8192",
                "rx-error": "1",
                "tx-error": "2",
                "rx-drop": "3",
                "tx-drop": "4",
            }
        ],
        "ip/dhcp-server/lease": [
            {
                "address": "192.0.2.88",
                "mac-address": "00:11:22:33:44:55",
                "host-name": "private-client",
            }
        ],
        "ip/arp": [
            {"address": "192.0.2.89", "mac-address": "00:11:22:33:44:66"}
        ],
        "interface/wireless/registration-table": [
            {
                "interface": "wlan1",
                "signal-strength": "-61dBm",
                "mac-address": "00:11:22:33:44:77",
                "host-name": "wireless-client",
            }
        ],
    }

    class FakeResponse:
        def __init__(self, value):
            self.value = value

        def raise_for_status(self):
            return None

        def json(self):
            return self.value

    class FakeClient:
        def __init__(self, *, verify, timeout, auth):
            assert verify is True
            assert timeout == 5.0
            assert auth == ("poller", "password")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, url):
            endpoint = url.split("/rest/", 1)[1]
            return FakeResponse(payloads[endpoint])

    monkeypatch.setattr(mikrotik.httpx, "AsyncClient", FakeClient)
    device = SimpleNamespace(
        name="routeros-rest-test",
        mgmt_ip="192.0.2.1",
        site=SimpleNamespace(code="REST"),
        credential_profile=SimpleNamespace(
            username="poller",
            secret_ciphertext=encrypt_secret("password"),
            port=443,
            verify_tls=True,
        ),
    )

    result = await _collect_rest(device)

    assert device.snmp_system_name == "lab-router"
    assert device.uptime_seconds == 93600
    assert device.cpu_usage_percent == 12
    assert device.memory_used_bytes == 512
    assert device.disk_used_bytes == 2048
    assert device.temperature_celsius == 45
    assert device.voltage_volts == 24.2
    assert device.dhcp_lease_count == 1
    assert device.arp_entry_count == 1
    assert result.interfaces[1]["in_octets"] == 4096
    assert result.interfaces[1]["out_discards"] == 4
    wireless_client_metric = MIKROTIK_WIRELESS_CLIENTS.labels(
        device.name, "wlan1", device.site.code
    )
    assert wireless_client_metric._value.get() == 1

    metrics = generate_latest().decode()
    assert "private-client" not in metrics
    assert "wireless-client" not in metrics
    assert "00:11:22:33:44:55" not in metrics
    assert "192.0.2.88" not in metrics


async def test_routeros_rest_probe_falls_back_to_v6_binary_api(monkeypatch):
    from app.collectors import mikrotik

    calls = []

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, *_args, **_kwargs):
            raise httpx.ConnectError("RouterOS v6 has no REST endpoint")

    class FakeBinaryApi:
        def __init__(self, address, port, username, password, verify_tls):
            calls.append((address, port, username, password, verify_tls))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def command(self, path):
            calls.append(path)
            return [{"version": "6.49"}]

    monkeypatch.setattr(mikrotik.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(mikrotik, "_BinaryApi", FakeBinaryApi)

    elapsed = await probe_routeros_api(
        "192.0.2.1", 443, "poller", "password", verify_tls=True
    )

    assert elapsed >= 0
    assert calls == [
        ("192.0.2.1", 8729, "poller", "password", True),
        "/system/resource/print",
    ]


async def test_binary_api_supports_legacy_v6_challenge_login(monkeypatch):
    api = _BinaryApi("192.0.2.1", 8728, "poller", "password", True)
    challenge = "00112233445566778899aabbccddeeff"
    responses = iter(
        [
            ["!done", f"=ret={challenge}"],
            ["!done"],
        ]
    )
    sent = []

    async def send_sentence(words):
        sent.append(words)

    async def read_sentence():
        return next(responses)

    monkeypatch.setattr(api, "_send_sentence", send_sentence)
    monkeypatch.setattr(api, "_read_sentence", read_sentence)

    await api._request(["/login"])

    digest = hashlib.md5(
        b"\x00password" + bytes.fromhex(challenge), usedforsecurity=False
    ).hexdigest()
    assert sent == [
        ["/login"],
        ["/login", "=name=poller", f"=response=00{digest}"],
    ]
    assert api._authenticated is True
