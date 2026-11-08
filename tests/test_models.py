import pytest
from app.models import Device, DeviceGroup, DeviceType, Site
from app.schemas import DeviceCreate, DeviceDetail, DeviceRead
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload


async def make_site(session, code="HQ"):
    site = Site(code=code, name=f"Site {code}")
    session.add(site)
    await session.flush()
    return site


async def test_create_device_with_defaults(session):
    site = await make_site(session)
    dev = Device(site_id=site.id, name="rtr1", mgmt_ip="192.168.88.1")
    session.add(dev)
    await session.commit()
    await session.refresh(dev)

    assert dev.id is not None
    assert dev.device_type is DeviceType.OTHER
    assert dev.is_active is True
    assert dev.poll_interval_seconds == 60
    assert dev.tags == {}
    assert dev.created_at is not None


async def test_schema_to_orm_roundtrip(session):
    site = await make_site(session)
    payload = DeviceCreate(
        site_id=site.id,
        name="mikrotik-1",
        mgmt_ip="10.0.0.1",
        mac="AA-BB-CC-DD-EE-FF",
        device_type="router",
        vendor="MikroTik",
        tags={"role": "edge"},
    )
    dev = Device(**payload.model_dump(exclude={"group_ids"}))
    session.add(dev)
    await session.commit()
    await session.refresh(dev)

    read = DeviceRead.model_validate(dev)
    assert str(read.mgmt_ip) == "10.0.0.1"
    assert read.mac == "aa:bb:cc:dd:ee:ff"
    assert read.device_type is DeviceType.ROUTER
    assert read.vendor == "mikrotik"
    assert read.tags == {"role": "edge"}


async def test_unique_device_name(session):
    site = await make_site(session)
    session.add_all(
        [
            Device(site_id=site.id, name="dup", mgmt_ip="10.0.0.1"),
            Device(site_id=site.id, name="dup", mgmt_ip="10.0.0.2"),
        ]
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_same_ip_allowed_twice(session):
    # IP is an attribute, not an identity (DHCP, re-addressing).
    site = await make_site(session)
    session.add_all(
        [
            Device(site_id=site.id, name="a", mgmt_ip="10.0.0.1"),
            Device(site_id=site.id, name="b", mgmt_ip="10.0.0.1"),
        ]
    )
    await session.commit()


async def test_site_with_devices_cannot_be_deleted(session):
    site = await make_site(session)
    session.add(Device(site_id=site.id, name="rtr1", mgmt_ip="10.0.0.1"))
    await session.commit()

    await session.delete(site)
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_device_cannot_be_its_own_parent(session):
    site = await make_site(session)
    dev = Device(site_id=site.id, name="rtr1", mgmt_ip="10.0.0.1")
    session.add(dev)
    await session.commit()

    dev.parent_device_id = dev.id
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_deleting_parent_nulls_child(session):
    site = await make_site(session)
    parent = Device(site_id=site.id, name="core", mgmt_ip="10.0.0.1")
    session.add(parent)
    await session.flush()
    child = Device(
        site_id=site.id, name="edge", mgmt_ip="10.0.0.2", parent_device_id=parent.id
    )
    session.add(child)
    await session.commit()

    await session.delete(parent)
    await session.commit()
    await session.refresh(child)
    assert child.parent_device_id is None


async def test_poll_interval_check(session):
    site = await make_site(session)
    session.add(
        Device(site_id=site.id, name="x", mgmt_ip="10.0.0.1", poll_interval_seconds=1)
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_groups_many_to_many(session):
    site = await make_site(session)
    core = DeviceGroup(name="Core routers")
    critical = DeviceGroup(name="Critical")
    dev = Device(site_id=site.id, name="rtr1", mgmt_ip="10.0.0.1", groups=[core, critical])
    session.add(dev)
    await session.commit()

    loaded = (
        await session.execute(
            select(DeviceGroup)
            .where(DeviceGroup.name == "Core routers")
            .options(selectinload(DeviceGroup.devices))
        )
    ).scalar_one()
    assert [d.name for d in loaded.devices] == ["rtr1"]


async def test_deleting_group_keeps_devices(session):
    site = await make_site(session)
    group = DeviceGroup(name="Temp")
    dev = Device(site_id=site.id, name="rtr1", mgmt_ip="10.0.0.1", groups=[group])
    session.add(dev)
    await session.commit()

    await session.delete(group)
    await session.commit()

    remaining = (await session.execute(select(Device))).scalars().all()
    assert len(remaining) == 1


async def test_detail_schema_with_eager_loading(session):
    site = await make_site(session)
    group = DeviceGroup(name="Core")
    parent = Device(site_id=site.id, name="core", mgmt_ip="10.0.0.1")
    session.add(parent)
    await session.flush()
    child = Device(
        site_id=site.id,
        name="edge",
        mgmt_ip="10.0.0.2",
        parent_device_id=parent.id,
        groups=[group],
    )
    session.add(child)
    await session.commit()

    loaded = (
        await session.execute(
            select(Device)
            .where(Device.name == "edge")
            .options(
                selectinload(Device.site),
                selectinload(Device.groups),
                selectinload(Device.parent),
            )
        )
    ).scalar_one()
    detail = DeviceDetail.model_validate(loaded)
    assert detail.site.code == "HQ"
    assert [g.name for g in detail.groups] == ["Core"]
    assert detail.parent is not None and detail.parent.name == "core"
    assert detail.model_dump(mode="json")["mgmt_ip"] == "10.0.0.2"
