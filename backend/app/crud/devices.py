"""Device data access."""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Device, DeviceGroup, DeviceType
from app.schemas import DeviceCreate, DeviceUpdate


async def list_devices(
    session: AsyncSession,
    *,
    site_id: int | None = None,
    is_active: bool | None = None,
    device_type: DeviceType | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Device], int]:
    """Return one filtered page of devices plus the total row count."""
    filters = []
    if site_id is not None:
        filters.append(Device.site_id == site_id)
    if is_active is not None:
        filters.append(Device.is_active.is_(is_active))
    if device_type is not None:
        filters.append(Device.device_type == device_type)

    total = (
        await session.scalar(
            select(func.count()).select_from(Device).where(*filters)
        )
        or 0
    )
    rows = await session.scalars(
        select(Device)
        .where(*filters)
        .order_by(Device.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total


async def get_device(session: AsyncSession, device_id: int) -> Device | None:
    return await session.get(Device, device_id)


async def list_devices_with_site(session: AsyncSession) -> list[Device]:
    """Every device with its site loaded, for status dashboards."""
    rows = await session.scalars(
        select(Device).options(selectinload(Device.site)).order_by(Device.id)
    )
    return list(rows)


async def get_device_detail(
    session: AsyncSession, device_id: int
) -> Device | None:
    """Load a device with every relationship DeviceDetail needs."""
    return await session.scalar(
        select(Device)
        .where(Device.id == device_id)
        .options(
            selectinload(Device.site),
            selectinload(Device.groups),
            selectinload(Device.parent),
            selectinload(Device.credential_profile),
        )
    )


async def get_devices_by_ids(
    session: AsyncSession, device_ids: list[int]
) -> list[Device]:
    if not device_ids:
        return []
    rows = await session.scalars(
        select(Device).where(Device.id.in_(device_ids))
    )
    return list(rows)


async def get_groups_by_ids(
    session: AsyncSession, group_ids: list[int]
) -> list[DeviceGroup]:
    if not group_ids:
        return []
    rows = await session.scalars(
        select(DeviceGroup).where(DeviceGroup.id.in_(group_ids))
    )
    return list(rows)


async def create_device(
    session: AsyncSession, payload: DeviceCreate, groups: list[DeviceGroup]
) -> Device:
    device = Device(**payload.model_dump(exclude={"group_ids"}))
    if groups:
        device.groups = groups
    session.add(device)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise
    return device


async def update_device(
    session: AsyncSession,
    device: Device,
    payload: DeviceUpdate,
    *,
    groups: list[DeviceGroup] | None = None,
    set_groups: bool = False,
) -> Device:
    changes = payload.model_dump(exclude_unset=True, exclude={"group_ids"})
    for field, value in changes.items():
        setattr(device, field, value)
    if set_groups:
        device.groups = groups or []
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise
    return device


async def delete_device(session: AsyncSession, device: Device) -> None:
    await session.delete(device)
    await session.commit()
