"""Schema tests: no database needed."""

import pytest
from app.models.enums import DeviceCheckType, DeviceType
from app.schemas import DeviceCreate, DeviceUpdate, SiteCreate
from pydantic import ValidationError


def make_device(**overrides):
    data = {"site_id": 1, "name": "core-rtr-1", "mgmt_ip": "192.168.88.1"}
    data.update(overrides)
    return DeviceCreate(**data)


def test_device_defaults():
    d = make_device()
    assert d.device_type is DeviceType.OTHER
    assert d.check_type is DeviceCheckType.PING_ONLY
    assert d.credential_profile_id is None
    assert d.poll_interval_seconds == 60
    assert d.tags == {}


@pytest.mark.parametrize(
    "raw",
    ["AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", "aabb.ccdd.eeff", "aabbccddeeff"],
)
def test_mac_is_normalized(raw):
    assert make_device(mac=raw).mac == "aa:bb:cc:dd:ee:ff"


def test_bad_mac_rejected():
    with pytest.raises(ValidationError):
        make_device(mac="not-a-mac")


def test_bad_ip_rejected():
    with pytest.raises(ValidationError):
        make_device(mgmt_ip="999.1.1.1")


def test_ipv6_accepted():
    assert make_device(mgmt_ip="2001:db8::1").mgmt_ip.version == 6


def test_poll_interval_bounds():
    with pytest.raises(ValidationError):
        make_device(poll_interval_seconds=5)
    with pytest.raises(ValidationError):
        make_device(poll_interval_seconds=7200)


def test_vendor_lowercased():
    assert make_device(vendor=" MikroTik ").vendor == "mikrotik"


def test_dump_is_orm_ready():
    data = make_device(mac="AA:BB:CC:DD:EE:FF", device_type="router").model_dump(
        exclude={"group_ids"}
    )
    assert data["mgmt_ip"] == "192.168.88.1"  # plain str for the INET column
    assert data["device_type"] is DeviceType.ROUTER


def test_update_only_sets_given_fields():
    patch = DeviceUpdate(name="renamed", mgmt_ip="10.0.0.9")
    assert patch.model_dump(exclude_unset=True) == {
        "name": "renamed",
        "mgmt_ip": "10.0.0.9",
    }


def test_site_code_pattern():
    SiteCreate(code="HQ-1", name="Head office")
    with pytest.raises(ValidationError):
        SiteCreate(code="bad code!", name="x")
