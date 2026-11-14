from types import SimpleNamespace

from app.collectors.generic_snmp import collector
from app.collectors.generic_snmp.collector import (
    _SYSTEM_OIDS,
    GenericSNMPCollector,
)
from app.services.credentials import decrypt_secret, encrypt_secret


class FakeEngine:
    def __init__(self):
        self.closed = False

    def close_dispatcher(self):
        self.closed = True


def _device():
    return SimpleNamespace(
        name="snmp-test",
        mgmt_ip="192.0.2.10",
        credential_profile=SimpleNamespace(port=161),
    )


async def test_system_poll_reads_standard_system_oids(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(
        collector,
        "_open_target",
        lambda device: _resolved((engine, object(), object())),
    )
    oids = {
        _SYSTEM_OIDS["name"]: "lab-linux",
        _SYSTEM_OIDS["description"]: "Linux test-agent",
        _SYSTEM_OIDS["uptime"]: 987654,
    }

    async def get(_engine, _auth, _target, requested):
        assert requested == list(_SYSTEM_OIDS.values())
        return oids

    monkeypatch.setattr(collector, "_get", get)
    result = await GenericSNMPCollector().collect_system(_device())

    assert result.name == "lab-linux"
    assert result.description == "Linux test-agent"
    assert result.uptime_seconds == 9876
    assert engine.closed


async def test_interface_poll_reads_64_bit_counters_status_and_crc(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(
        collector,
        "_open_target",
        lambda device: _resolved((engine, object(), object())),
    )
    values = {
        "1.3.6.1.2.1.31.1.1.1.1": {2: "eth0"},
        "1.3.6.1.2.1.2.2.1.2": {},
        "1.3.6.1.2.1.31.1.1.1.18": {2: "uplink"},
        "1.3.6.1.2.1.31.1.1.1.15": {2: 1000},
        "1.3.6.1.2.1.31.1.1.1.6": {2: 2**40},
        "1.3.6.1.2.1.31.1.1.1.10": {2: 2**41},
        "1.3.6.1.2.1.2.2.1.10": {},
        "1.3.6.1.2.1.2.2.1.16": {},
        "1.3.6.1.2.1.2.2.1.14": {2: 3},
        "1.3.6.1.2.1.2.2.1.20": {2: 4},
        "1.3.6.1.2.1.2.2.1.13": {2: 5},
        "1.3.6.1.2.1.2.2.1.19": {2: 6},
        "1.3.6.1.2.1.2.2.1.7": {2: 1},
        "1.3.6.1.2.1.2.2.1.8": {2: 1},
        "1.3.6.1.2.1.10.7.2.1.3": {2: 7},
    }

    async def walk(_engine, _auth, _target, oid):
        return values[oid]

    monkeypatch.setattr(collector, "_walk", walk)
    interfaces = await GenericSNMPCollector().collect_interfaces(_device())

    assert interfaces[2].name == "eth0"
    assert interfaces[2].alias == "uplink"
    assert interfaces[2].admin == 1
    assert interfaces[2].oper == 1
    assert interfaces[2].speed == 1000
    assert interfaces[2].in_octets == 2**40
    assert interfaces[2].out_octets == 2**41
    assert interfaces[2].crc_errors == 7
    assert engine.closed


async def test_health_poll_aggregates_host_resources_and_entity_sensors(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(
        collector,
        "_open_target",
        lambda device: _resolved((engine, object(), object())),
    )
    tables = {
        collector._HOST_CPU_LOAD: {1: 20, 2: 40},
        collector._HOST_STORAGE["type"]: {1: 2, 2: 4},
        collector._HOST_STORAGE["allocation_units"]: {1: 4096, 2: 1},
        collector._HOST_STORAGE["size"]: {1: 100, 2: 50},
        collector._HOST_STORAGE["used"]: {1: 75, 2: 25},
        collector._ENTITY_SENSOR_COLUMNS["type"]: {1: 8, 2: 4, 3: 10},
        collector._ENTITY_SENSOR_COLUMNS["scale"]: {1: 10, 2: 10, 3: 10},
        collector._ENTITY_SENSOR_COLUMNS["precision"]: {1: 1, 2: 1, 3: 0},
        collector._ENTITY_SENSOR_COLUMNS["value"]: {1: 450, 2: 241, 3: 1200},
    }

    async def walk(_engine, _auth, _target, oid):
        return tables[oid]

    monkeypatch.setattr(collector, "_walk", walk)
    result = await GenericSNMPCollector().collect_health(_device())

    assert result.cpu_usage_percent == 30
    assert result.memory_total_bytes == 409600
    assert result.memory_used_bytes == 307200
    assert result.temperature_celsius == 45
    assert result.voltage_volts == 24.1
    assert result.fan_speed_rpm == 1200
    assert engine.closed


async def test_fernet_secret_round_trip(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    ciphertext = encrypt_secret("private-community")
    assert ciphertext != "private-community"
    assert decrypt_secret(ciphertext) == "private-community"


async def _resolved(value):
    return value
