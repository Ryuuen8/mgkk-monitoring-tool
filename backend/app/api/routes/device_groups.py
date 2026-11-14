"""Device group CRUD routes."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import device_groups as crud
from app.crud import devices as devices_crud
from app.db.session import get_session
from app.schemas import (
    DeviceGroupCreate,
    DeviceGroupRead,
    DeviceGroupUpdate,
    DeviceRead,
    GroupMembersUpdate,
    Page,
)

router = APIRouter(prefix="/device-groups", tags=["device-groups"])

GROUP_NOT_FOUND = "device group not found"
GROUP_NAME_CONFLICT = "a device group with this name already exists"
MEMBER_NOT_FOUND = "device is not a member of this group"


def _reject_nulls(changes: dict[str, Any]) -> None:
    if "name" in changes and changes["name"] is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "fields may not be null: ['name']",
        )


@router.get("", response_model=Page[DeviceGroupRead])
async def list_groups(
    session: Annotated[AsyncSession, Depends(get_session)],
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[DeviceGroupRead]:
    rows, total = await crud.list_groups(
        session, q=q, limit=limit, offset=offset
    )
    return Page(
        items=[DeviceGroupRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{group_id}", response_model=DeviceGroupRead)
async def get_group(
    group_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceGroupRead:
    group = await crud.get_group(session, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, GROUP_NOT_FOUND)
    return DeviceGroupRead.model_validate(group)


@router.post(
    "", response_model=DeviceGroupRead, status_code=status.HTTP_201_CREATED
)
async def create_group(
    payload: DeviceGroupCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceGroupRead:
    try:
        group = await crud.create_group(session, payload)
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, GROUP_NAME_CONFLICT
        ) from None
    return DeviceGroupRead.model_validate(group)


@router.patch("/{group_id}", response_model=DeviceGroupRead)
async def update_group(
    group_id: int,
    payload: DeviceGroupUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceGroupRead:
    group = await crud.get_group(session, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, GROUP_NOT_FOUND)

    _reject_nulls(payload.model_dump(exclude_unset=True))
    try:
        group = await crud.update_group(session, group, payload)
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, GROUP_NAME_CONFLICT
        ) from None
    return DeviceGroupRead.model_validate(group)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    group = await crud.get_group(session, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, GROUP_NOT_FOUND)
    await crud.delete_group(session, group)


@router.get("/{group_id}/devices", response_model=Page[DeviceRead])
async def list_group_devices(
    group_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[DeviceRead]:
    if await crud.get_group(session, group_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, GROUP_NOT_FOUND)
    rows, total = await crud.list_group_devices(
        session, group_id, limit=limit, offset=offset
    )
    return Page(
        items=[DeviceRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/{group_id}/devices", status_code=status.HTTP_204_NO_CONTENT)
async def add_group_devices(
    group_id: int,
    payload: GroupMembersUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    group = await crud.get_group_with_devices(session, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, GROUP_NOT_FOUND)

    devices = await devices_crud.get_devices_by_ids(session, payload.device_ids)
    missing = sorted(
        set(payload.device_ids) - {device.id for device in devices}
    )
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"device(s) not found: {missing}",
        )
    await crud.add_group_devices(session, group, devices)


@router.delete(
    "/{group_id}/devices/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_group_device(
    group_id: int,
    device_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    group = await crud.get_group_with_devices(session, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, GROUP_NOT_FOUND)
    if not await crud.remove_group_device(session, group, device_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, MEMBER_NOT_FOUND)
