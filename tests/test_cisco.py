from types import SimpleNamespace
from typing import Any

from app.collectors.base import HealthData
from app.collectors.cisco import mibs
from app.collectors.cisco import restconf as restconf_module
from app.collectors.cisco.collector import (
    _merge_neighbors,
    _state_ok,
    poll_cdp_neighbors,
    poll_cisco_health,
    poll_stack_members,
)
from app.collectors.cisco.restconf import (
    _health,
    _interfaces,
    _neighbors,
    _system,
)
from app.collectors.generic_snmp import collector as generic


def _device() -> SimpleNamespace:
    return SimpleNamespace(name="cisco-test")


def test_cisco_oids_live_only_in_the_cisco_package():
    import pathlib

    collectors = pathlib.Path(generic.__file__).parent.parent
    for package in ("generic_snmp", "mikrotik"):
        for path in (collectors / package).rglob("*.py"):
            contents = path.read_text(encoding="utf-8")
            assert "1.3.6.1.4.1.9" not in contents, path


def test_envmon_state_ignores_not_present_entries():
    assert _state_ok({1: 1, 2: 5}) is True
    assert _state_ok({1: 1, 2: 3}) is False
    assert _state_ok({1: 5}) is None
    assert _state_ok({}) is None


def test_merge_neighbors_deduplicates_and_sorts():
    from app.collectors.base import NeighborData

    merged = _merge_neighbors(
        [
            NeighborData(
                protocol="cdp",
                local_interface="Gi0/1",
                remote_device="sw2",
                remote_interface="Gi0/2",
            ),
            NeighborData(
                protocol="cdp",
                local_interface="Gi0/1",
                remote_device="sw2",
                remote_interface="Gi0/2",
            ),
            NeighborData(
                protocol="lldp",
                local_interface="Gi0/2",
                remote_device="sw3",
            ),
        ]
    )
    assert [item.protocol for item in merged] == ["cdp", "lldp"]
    assert merged[0].remote_device == "sw2"


async def test_cdp_neighbors_use_shared_if_mib(monkeypatch):
    tables: dict[str, dict[str, Any]] = {
        mibs.CDP_COLUMNS["device_id"]: {"1.1": "core-sw"},
        mibs.CDP_COLUMNS["device_port"]: {"1.1": "Gi0/24"},
        mibs.CDP_COLUMNS["platform"]: {"1.1": "cisco WS-C3750"},
        mibs.CDP_COLUMNS["address"]: {"1.1": b"\xc0\x00\x02\x0a"},
        mibs.CDP_COLUMNS["capabilities"]: {"1.1": 0b00010001},
        mibs.CDP_COLUMNS["address_type"]: {"1.1": 1},
        mibs.CDP_COLUMNS["version"]: {"1.1": "Cisco IOS"},
        mibs.CDP_COLUMNS["native_vlan"]: {"1.1": 10},
        mibs.CDP_COLUMNS["duplex"]: {"1.1": 1},
    }
    interface_names = {1: "GigabitEthernet0/1"}

    async def walk_raw(_engine, _auth, _target, oid):
        return tables[oid]

    async def walk(_engine, _auth, _target, oid):
        assert oid == generic.IF_NAME
        return interface_names

    monkeypatch.setattr(generic, "snmp_walk_raw", walk_raw)
    monkeypatch.setattr(generic, "snmp_walk", walk)
    monkeypatch.setattr(generic, "decode_address", lambda value: "192.0.2.10")

    neighbors = await poll_cdp_neighbors(object(), object(), object())

    assert len(neighbors) == 1
    neighbor = neighbors[0]
    assert neighbor.protocol == "cdp"
    assert neighbor.local_interface == "GigabitEthernet0/1"
    assert neighbor.remote_device == "core-sw"
    assert neighbor.remote_interface == "Gi0/24"
    assert neighbor.remote_address == "192.0.2.10"
    assert neighbor.capabilities == "router,host"


async def test_stack_members_snapshot_uses_stackwise_mib(monkeypatch):
    tables = {
        mibs.STACKWISE_COLUMNS["role"]: {1: 1, 2: 2},
        mibs.STACKWISE_COLUMNS["state"]: {1: 4, 2: 4},
        mibs.STACKWISE_COLUMNS["software_priority"]: {1: 15, 2: 14},
        mibs.STACKWISE_COLUMNS["hardware_priority"]: {1: 1, 2: 2},
        mibs.STACKWISE_COLUMNS["mac_address"]: {1: "00:11:22:33:44:55"},
        mibs.STACKWISE_COLUMNS["software_image"]: {1: "cat3k_caa"},
    }

    async def safe_walk(_engine, _auth, _target, oid, **_kwargs):
        return tables.get(oid, {})

    monkeypatch.setattr(generic, "safe_walk", safe_walk)

    members = await poll_stack_members(object(), object(), object(), "stack")

    assert members[0]["role"] == "master"
    assert members[0]["state"] == "ready"
    assert members[0]["software_priority"] == 15
    assert members[1]["role"] == "member"


def test_restconf_parsers_normalise_interface_and_health_payloads():
    interfaces = _interfaces(
        {
            "Cisco-IOS-XE-interfaces-oper:interfaces": {
                "interface": [
                    {
                        "name": "GigabitEthernet1",
                        "if-index": 1,
                        "description": "uplink",
                        "admin-status": "if-state-up",
                        "oper-status": "if-oper-state-ready",
                        "speed": "1000000000",
                        "statistics": {
                            "in-octets": 100,
                            "out-octets": 200,
                            "in-errors": 1,
                            "out-errors": 2,
                            "in-discards": 3,
                            "out-discards": 4,
                            "in-crc-errors": 5,
                        },
                    }
                ]
            }
        }
    )
    interface = interfaces[1]
    assert interface.name == "GigabitEthernet1"
    assert interface.admin == 1
    assert interface.oper == 1
    assert interface.speed == 1000
    assert interface.crc_errors == 5

    health = _health(
        {"Cisco-IOS-XE-process-cpu-oper:cpu-utilization": {"one-minute": 42}},
        {
            "Cisco-IOS-XE-memory-oper:memory-statistics": {
                "memory-statistic": [
                    {"total-memory": 1000, "used-memory": 400}
                ]
            }
        },
    )
    assert health.cpu_usage_percent == 42.0
    assert health.memory_total_bytes == 1000
    assert health.memory_used_bytes == 400

    system = _system({"hostname": "edge-1"})
    assert system.name == "edge-1"
    assert system.description == "Cisco IOS-XE RESTCONF"


def test_restconf_neighbors_parse_cdp_and_lldp():
    neighbors = _neighbors(
        {
            "cdp-neighbor-detail": [
                {
                    "local-interface-name": "Gi1",
                    "device-name": "sw2",
                    "port-id": "Gi0/2",
                    "platform-name": "C9300",
                    "ip-address": "192.0.2.2",
                    "capabilities": "switch",
                }
            ]
        },
        {
            "lldp-entry": [
                {
                    "local-interface": "Gi2",
                    "system-name": "sw3",
                    "port-id": "Gi0/3",
                    "system-description": "Cisco IOS",
                    "management-address": "192.0.2.3",
                    "capabilities": "bridge",
                }
            ]
        },
    )
    assert [item.protocol for item in neighbors] == ["cdp", "lldp"]
    assert neighbors[0].remote_device == "sw2"
    assert neighbors[1].remote_interface == "Gi0/3"


async def test_cisco_health_merges_standard_fallback(monkeypatch):
    from app.collectors.cisco.collector import poll_cisco_health

    tables = {
        mibs.CPU_COLUMNS["one_minute"]: {1: 30},
        mibs.MEMORY_COLUMNS["used"]: {1: 300},
        mibs.MEMORY_COLUMNS["free"]: {1: 700},
        mibs.ENVMON_TEMPERATURE_VALUE_REV1: {1: 41},
        mibs.ENVMON_VOLTAGE_VALUE: {1: 12_100},
        mibs.ENVMON_FAN_STATE: {1: 1, 2: 5},
        mibs.ENVMON_SUPPLY_STATE: {1: 1},
    }

    async def safe_walk(_engine, _auth, _target, oid, **_kwargs):
        return tables.get(oid, {})

    monkeypatch.setattr(generic, "safe_walk", safe_walk)

    health = await poll_cisco_health(
        object(),
        object(),
        object(),
        HealthData(cpu_usage_percent=10.0),
        "cisco-test",
    )
    assert health.cpu_usage_percent == 30.0
    assert health.memory_total_bytes == 1000
    assert health.memory_used_bytes == 300
    assert health.temperature_celsius == 41.0
    assert health.voltage_volts == 12.1
    assert health.fans_ok is True
    assert health.power_supplies_ok is True


async def test_cisco_snmp_prefers_five_minute_cpu(monkeypatch):
    tables = {
        mibs.CPU_COLUMNS["five_minutes"]: {1: 12},
        mibs.CPU_COLUMNS["one_minute"]: {1: 30},
        mibs.CPU_COLUMNS["five_seconds"]: {1: 90},
    }

    async def safe_walk(_engine, _auth, _target, oid, **_kwargs):
        return tables.get(oid, {})

    monkeypatch.setattr(generic, "safe_walk", safe_walk)

    health = await poll_cisco_health(
        object(),
        object(),
        object(),
        HealthData(),
        "cisco-test",
    )
    assert health.cpu_usage_percent == 12.0


def test_restconf_health_prefers_five_minute_cpu():
    health = restconf_module._health(
        {
            "Cisco-IOS-XE-process-cpu-oper:cpu-utilization": {
                "five-minutes": 35,
                "one-minute": 42,
            }
        },
        None,
    )
    assert health.cpu_usage_percent == 35.0


def test_restconf_parses_ietf_interfaces_state():
    interfaces = _interfaces(
        {
            "ietf-interfaces:interfaces-state": {
                "interface": [
                    {
                        "name": "GigabitEthernet2",
                        "description": "ietf uplink",
                        "admin-status": "up",
                        "oper-status": "up",
                        "speed": "10000000000",
                        "statistics": {
                            "in-octets": 10,
                            "out-octets": 20,
                            "in-errors": 1,
                            "out-errors": 2,
                            "in-discards": 3,
                            "out-discards": 4,
                            "in-crc-errors": 5,
                        },
                    }
                ]
            }
        }
    )
    interface = interfaces[1]
    assert interface.name == "GigabitEthernet2"
    assert interface.alias == "ietf uplink"
    assert interface.admin == 1
    assert interface.oper == 1
    assert interface.speed == 10_000
    assert interface.in_octets == 10
    assert interface.crc_errors == 5


async def test_restconf_interfaces_fall_back_to_ietf_state(monkeypatch):
    paths: list[str] = []

    async def fake_get(_device, path):
        paths.append(path)
        if path.startswith("Cisco-IOS-XE-interfaces-oper"):
            raise restconf_module.RestconfError("404")
        return {
            "ietf-interfaces:interfaces-state": {
                "interface": [
                    {
                        "name": "GigabitEthernet3",
                        "admin-status": "down",
                        "oper-status": "down",
                    }
                ]
            }
        }

    monkeypatch.setattr(restconf_module, "_get", fake_get)

    payload = await restconf_module._interfaces_payload(_device())
    interfaces = restconf_module._interfaces(payload)

    assert paths == [
        "Cisco-IOS-XE-interfaces-oper:interfaces/interface",
        "ietf-interfaces:interfaces-state",
    ]
    assert interfaces[1].name == "GigabitEthernet3"
    assert interfaces[1].admin == 2
    assert interfaces[1].oper == 2
