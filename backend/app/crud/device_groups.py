"""Device group data access."""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Device, DeviceGroup
from app.schemas import DeviceGroupCreate, DeviceGroupUpdate


async def list_groups(
    session: AsyncSession,
    *,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[DeviceGroup], int]:
    filters = []
    if q is not None and q.strip():
        filters.append(
            func.lower(DeviceGroup.name).like(f"%{q.strip().lower()}%")
        )
    total = (
        await session.scalar(
            select(func.count()).select_from(DeviceGroup).where(*filters)
        )
        or 0
    )
    rows = await session.scalars(
        select(DeviceGroup)
        .where(*filters)
        .order_by(DeviceGroup.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total


async def get_group(
    session: AsyncSession, group_id: int
) -> DeviceGroup | None:
    return await session.get(DeviceGroup, group_id)


async def get_group_with_devices(
    session: AsyncSession, group_id: int
) -> DeviceGroup | None:
    return await session.scalar(
        select(DeviceGroup)
        .where(DeviceGroup.id == group_id)
        .options(selectinload(DeviceGroup.devices))
    )


async def get_group_by_name(
    session: AsyncSession, name: str
) -> DeviceGroup | None:
    return await session.scalar(
        select(DeviceGroup).where(DeviceGroup.name == name)
    )


async def create_group(
    session: AsyncSession, payload: DeviceGroupCreate
) -> DeviceGroup:
    group = DeviceGroup(**payload.model_dump())
    session.add(group)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise
    await session.refresh(group)
    return group


async def update_group(
    session: AsyncSession, group: DeviceGroup, payload: DeviceGroupUpdate
) -> DeviceGroup:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise
    await session.refresh(group)
    return group


async def delete_group(session: AsyncSession, group: DeviceGroup) -> None:
    await session.delete(group)
    await session.commit()


async def list_group_devices(
    session: AsyncSession,
    group_id: int,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Device], int]:
    total = (
        await session.scalar(
            select(func.count())
            .select_from(Device)
            .join(Device.groups)
            .where(DeviceGroup.id == group_id)
        )
        or 0
    )
    rows = await session.scalars(
        select(Device)
        .join(Device.groups)
        .where(DeviceGroup.id == group_id)
        .order_by(Device.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total


async def add_group_devices(
    session: AsyncSession, group: DeviceGroup, devices: list[Device]
) -> None:
    """Add devices that are not members yet. `group.devices` must be loaded."""
    existing = {device.id for device in group.devices}
    for device in devices:
        if device.id not in existing:
            group.devices.append(device)
    await session.commit()


async def remove_group_device(
    session: AsyncSession, group: DeviceGroup, device_id: int
) -> bool:
    """Remove one member. `group.devices` must be loaded."""
    for device in group.devices:
        if device.id == device_id:
            group.devices.remove(device)
            await session.commit()
            return True
    return False
