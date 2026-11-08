"""Device CRUD routes."""

import math
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import devices as crud
from app.crud import sites as sites_crud
from app.db.session import get_session
from app.models import (
    CredentialProfile,
    CredentialType,
    DeviceCheckType,
    DeviceGroup,
    DeviceType,
)
from app.schemas import (
    DeviceCreate,
    DeviceDetail,
    DeviceMetrics,
    DeviceRead,
    DeviceStatusList,
    DeviceStatusRead,
    DeviceUpdate,
    MetricPoint,
    Page,
)
from app.services import prometheus

router = APIRouter(prefix="/devices", tags=["devices"])

DEVICE_NOT_FOUND = "device not found"
DEVICE_NAME_CONFLICT = "a device with this name already exists"
SITE_NOT_FOUND = "site not found"
PARENT_NOT_FOUND = "parent device not found"
SELF_PARENT = "device cannot be its own parent"

# Fields that map to NOT NULL columns; an explicit null in PATCH is a client
# error, not a conflict with an existing row.
REQUIRED_FIELDS = (
    "site_id",
    "name",
    "mgmt_ip",
    "device_type",
    "check_type",
    "poll_interval_seconds",
    "is_active",
    "tags",
)


def _reject_nulls(changes: dict[str, Any]) -> None:
    nulls = sorted(
        field
        for field in REQUIRED_FIELDS
        if field in changes and changes[field] is None
    )
    if nulls:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"fields may not be null: {nulls}",
        )


async def _resolve_groups(
    session: AsyncSession, group_ids: list[int]
) -> list[DeviceGroup]:
    groups = await crud.get_groups_by_ids(session, group_ids)
    missing = sorted(set(group_ids) - {group.id for group in groups})
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"device group(s) not found: {missing}",
        )
    return groups


async def _check_site(session: AsyncSession, site_id: int) -> None:
    if await sites_crud.get_site(session, site_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, SITE_NOT_FOUND)


async def _check_parent(
    session: AsyncSession, parent_device_id: int, device_id: int | None = None
) -> None:
    if device_id is not None and parent_device_id == device_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, SELF_PARENT)
    if await crud.get_device(session, parent_device_id) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, PARENT_NOT_FOUND
        )


async def _check_credential_profile(
    session: AsyncSession,
    check_type: DeviceCheckType,
    credential_profile_id: int | None,
) -> None:
    if check_type == DeviceCheckType.PING_ONLY:
        if credential_profile_id is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "ping-only checks must not have a credential profile",
            )
        return
    if credential_profile_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "this check type requires a credential profile",
        )
    profile = await session.get(CredentialProfile, credential_profile_id)
    if profile is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "credential profile not found"
        )
    expected_type = (
        CredentialType.SNMP_V2C
        if check_type is DeviceCheckType.SNMP
        else CredentialType.ROUTEROS_API
    )
    if profile.credential_type != expected_type:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "credential profile type does not match the device check type",
        )


def _prom_label(value: str) -> str:
    """Escape a PromQL label value."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _vector_by_device(result: list[dict[str, Any]]) -> dict[str, float]:
    """Map a Prometheus instant vector's `device` label to its sample value."""
    values: dict[str, float] = {}
    for series in result:
        device = series.get("metric", {}).get("device")
        sample = series.get("value")
        if not device or not isinstance(sample, list) or len(sample) < 2:
            continue
        try:
            values[device] = float(sample[1])
        except (TypeError, ValueError):
            continue
    return values


def _matrix_points(result: list[dict[str, Any]]) -> list[MetricPoint]:
    """Flatten a Prometheus range matrix into finite, time-sorted points."""
    points: list[MetricPoint] = []
    for series in result:
        for sample in series.get("values") or []:
            if not isinstance(sample, list) or len(sample) < 2:
                continue
            try:
                timestamp = float(sample[0])
                value = float(sample[1])
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                points.append(MetricPoint(t=timestamp, value=value))
    points.sort(key=lambda point: point.t)
    return points


@router.get("/status", response_model=DeviceStatusList)
async def list_device_status(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceStatusList:
    """Latest up/latency/loss per device, sourced from Prometheus.

    Prometheus being down degrades to nulls instead of failing the dashboard.
    """
    devices = await crud.list_devices_with_site(session)
    up: dict[str, float] = {}
    latency: dict[str, float] = {}
    loss: dict[str, float] = {}
    try:
        up = _vector_by_device(await prometheus.query("device_up"))
        latency = _vector_by_device(
            await prometheus.query("ping_latency_seconds")
        )
        loss = _vector_by_device(
            await prometheus.query("ping_packet_loss_ratio")
        )
    except prometheus.PrometheusError:
        pass

    items = []
    for device in devices:
        up_value = up.get(device.name)
        latency_s = latency.get(device.name)
        loss_ratio = loss.get(device.name)
        items.append(
            DeviceStatusRead(
                device_id=device.id,
                name=device.name,
                site_code=device.site.code,
                up=None if up_value is None else up_value >= 1,
                latency_ms=(
                    latency_s * 1000
                    if latency_s is not None and math.isfinite(latency_s)
                    else None
                ),
                packet_loss=(
                    loss_ratio
                    if loss_ratio is not None and math.isfinite(loss_ratio)
                    else None
                ),
                last_seen_at=device.last_seen_at,
            )
        )
    return DeviceStatusList(items=items)


@router.get("/{device_id}/metrics", response_model=DeviceMetrics)
async def get_device_metrics(
    device_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    range_minutes: int = Query(default=60, ge=5, le=1440),
    step_seconds: int = Query(default=30, ge=10, le=3600),
) -> DeviceMetrics:
    """Prometheus range data for the device latency chart."""
    device = await crud.get_device_detail(session, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, DEVICE_NOT_FOUND)

    end = datetime.now(UTC)
    start = end - timedelta(minutes=range_minutes)
    selector = f'device="{_prom_label(device.name)}"'
    try:
        latency = await prometheus.query_range(
            f"ping_latency_seconds{{{selector}}}",
            start=start,
            end=end,
            step_seconds=step_seconds,
        )
        uptime = await prometheus.query_range(
            f"device_up{{{selector}}}",
            start=start,
            end=end,
            step_seconds=step_seconds,
        )
        loss = await prometheus.query_range(
            f"ping_packet_loss_ratio{{{selector}}}",
            start=start,
            end=end,
            step_seconds=step_seconds,
        )
    except prometheus.PrometheusError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"prometheus query failed: {exc}"
        ) from exc

    return DeviceMetrics(
        device_id=device.id,
        name=device.name,
        site_code=device.site.code,
        range_seconds=range_minutes * 60,
        step_seconds=step_seconds,
        latency=_matrix_points(latency),
        uptime=_matrix_points(uptime),
        packet_loss=_matrix_points(loss),
    )


@router.get("", response_model=Page[DeviceRead])
async def list_devices(
    session: Annotated[AsyncSession, Depends(get_session)],
    site_id: int | None = None,
    is_active: bool | None = None,
    device_type: DeviceType | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[DeviceRead]:
    rows, total = await crud.list_devices(
        session,
        site_id=site_id,
        is_active=is_active,
        device_type=device_type,
        limit=limit,
        offset=offset,
    )
    return Page(
        items=[DeviceRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{device_id}", response_model=DeviceDetail)
async def get_device(
    device_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceDetail:
    device = await crud.get_device_detail(session, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, DEVICE_NOT_FOUND)
    return DeviceDetail.model_validate(device)


@router.post("", response_model=DeviceDetail, status_code=status.HTTP_201_CREATED)
async def create_device(
    payload: DeviceCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceDetail:
    await _check_site(session, payload.site_id)
    await _check_credential_profile(
        session, payload.check_type, payload.credential_profile_id
    )
    if payload.parent_device_id is not None:
        await _check_parent(session, payload.parent_device_id)
    groups = await _resolve_groups(session, payload.group_ids)

    try:
        device = await crud.create_device(session, payload, groups)
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, DEVICE_NAME_CONFLICT
        ) from None

    detail = await crud.get_device_detail(session, device.id)
    if detail is None:  # pragma: no cover - just committed
        raise HTTPException(status.HTTP_404_NOT_FOUND, DEVICE_NOT_FOUND)
    return DeviceDetail.model_validate(detail)


@router.patch("/{device_id}", response_model=DeviceDetail)
async def update_device(
    device_id: int,
    payload: DeviceUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceDetail:
    device = await crud.get_device_detail(session, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, DEVICE_NOT_FOUND)

    changes = payload.model_dump(exclude_unset=True)
    _reject_nulls(changes)
    if "site_id" in changes:
        await _check_site(session, changes["site_id"])
    if changes.get("parent_device_id") is not None:
        await _check_parent(session, changes["parent_device_id"], device_id)
    await _check_credential_profile(
        session,
        changes.get("check_type", device.check_type),
        changes.get("credential_profile_id", device.credential_profile_id),
    )
    groups = await _resolve_groups(session, changes.get("group_ids") or [])

    try:
        await crud.update_device(
            session,
            device,
            payload,
            groups=groups,
            set_groups="group_ids" in changes,
        )
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, DEVICE_NAME_CONFLICT
        ) from None

    detail = await crud.get_device_detail(session, device_id)
    if detail is None:  # pragma: no cover - row still exists
        raise HTTPException(status.HTTP_404_NOT_FOUND, DEVICE_NOT_FOUND)
    return DeviceDetail.model_validate(detail)


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    device = await crud.get_device(session, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, DEVICE_NOT_FOUND)
    await crud.delete_device(session, device)
