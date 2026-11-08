"""Device CRUD routes."""

import math
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import devices as crud
from app.crud import sites as sites_crud
from app.db.session import get_session
from app.models import (
    CollectorType,
    CredentialProfile,
    CredentialType,
    DeviceCheckType,
    DeviceGroup,
    DeviceType,
    NetworkInterface,
)
from app.schemas import (
    DeviceCreate,
    DeviceDetail,
    DeviceMetrics,
    DeviceRead,
    DeviceStatusList,
    DeviceStatusRead,
    DeviceUpdate,
    InterfaceMetrics,
    LinkSpeedOverrideUpdate,
    MetricPoint,
    NetworkInterfaceRead,
    Page,
)
from app.services import fingerprint as fingerprint_service
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
    "collector",
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
    is_snmp_profile = profile.credential_type in {
        CredentialType.SNMP_V2C,
        CredentialType.SNMP_V3,
    }
    if (check_type is DeviceCheckType.SNMP and not is_snmp_profile) or (
        check_type is DeviceCheckType.ROUTEROS_API
        and profile.credential_type is not CredentialType.ROUTEROS_API
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "credential profile type does not match the device check type",
        )


def _check_collector(check_type: DeviceCheckType, collector: CollectorType) -> None:
    if (
        check_type is DeviceCheckType.ROUTEROS_API
        and collector is not CollectorType.MIKROTIK
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "RouterOS API checks require the MikroTik collector",
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


@router.get("/fingerprint")
def fingerprint_device(ip: str = Query(..., min_length=1)) -> dict[str, object]:
    """Probe a host and suggest a device type from its open ports."""
    result = fingerprint_service.fingerprint(ip)
    return {
        "ip": result.ip,
        "open_ports": result.open_ports,
        "suggested_device_type": result.suggested_device_type,
        "reason": result.reason,
    }


@router.get(
    "/{device_id}/interfaces", response_model=list[NetworkInterfaceRead]
)
async def list_device_interfaces(
    device_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[NetworkInterfaceRead]:
    device = await crud.get_device(session, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, DEVICE_NOT_FOUND)
    rows = await session.scalars(
        select(NetworkInterface)
        .where(NetworkInterface.device_id == device_id)
        .order_by(NetworkInterface.if_index)
    )
    return [NetworkInterfaceRead.model_validate(row) for row in rows]


@router.patch(
    "/{device_id}/interfaces/{interface_id}",
    response_model=NetworkInterfaceRead,
)
async def update_interface_link_speed(
    device_id: int,
    interface_id: int,
    payload: LinkSpeedOverrideUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NetworkInterfaceRead:
    row = await session.scalar(
        select(NetworkInterface).where(
            NetworkInterface.id == interface_id,
            NetworkInterface.device_id == device_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "interface not found")
    row.link_speed_override_mbps = payload.link_speed_override_mbps
    await session.commit()
    await session.refresh(row)
    return NetworkInterfaceRead.model_validate(row)


@router.get(
    "/{device_id}/interfaces/{interface_id}/metrics",
    response_model=InterfaceMetrics,
)
async def get_interface_metrics(
    device_id: int,
    interface_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    range_hours: int = Query(default=24, ge=24, le=720),
    step_seconds: int = Query(default=300, ge=30, le=3600),
) -> InterfaceMetrics:
    if range_hours not in {24, 168, 720}:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "range_hours must be 24, 168, or 720",
        )
    row = await session.scalar(
        select(NetworkInterface).where(
            NetworkInterface.id == interface_id,
            NetworkInterface.device_id == device_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "interface not found")
    device = await crud.get_device_detail(session, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, DEVICE_NOT_FOUND)
    end = datetime.now(UTC)
    start = end - timedelta(hours=range_hours)
    selector = (
        f'device="{_prom_label(device.name)}",'
        f'interface="{_prom_label(row.name)}",'
        f'site="{_prom_label(device.site.code)}"'
    )
    rate_window = max(device.poll_interval_seconds * 2, 300)
    queries = {
        "in_bits_per_second": (
            f"rate(interface_in_bytes_total{{{selector}}}[{rate_window}s]) * 8"
        ),
        "out_bits_per_second": (
            f"rate(interface_out_bytes_total{{{selector}}}[{rate_window}s]) * 8"
        ),
        "in_errors_per_second": (
            f"rate(interface_in_errors_total{{{selector}}}[{rate_window}s])"
        ),
        "out_errors_per_second": (
            f"rate(interface_out_errors_total{{{selector}}}[{rate_window}s])"
        ),
        "in_discards_per_second": (
            f"rate(interface_in_discards_total{{{selector}}}[{rate_window}s])"
        ),
        "out_discards_per_second": (
            f"rate(interface_out_discards_total{{{selector}}}[{rate_window}s])"
        ),
        "in_utilization": f"interface_in_link_utilization_ratio{{{selector}}}",
        "out_utilization": f"interface_out_link_utilization_ratio{{{selector}}}",
    }
    try:
        result = {
            key: _matrix_points(
                await prometheus.query_range(
                    query, start=start, end=end, step_seconds=step_seconds
                )
            )
            for key, query in queries.items()
        }
    except prometheus.PrometheusError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"prometheus query failed: {exc}"
        ) from exc
    return InterfaceMetrics(
        interface_id=row.id,
        interface_name=row.name,
        range_seconds=range_hours * 3600,
        step_seconds=step_seconds,
        **result,
    )


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
    _check_collector(payload.check_type, payload.collector)
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
    _check_collector(
        changes.get("check_type", device.check_type),
        changes.get("collector", device.collector),
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
