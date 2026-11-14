import asyncio
import json
import math
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import device_groups as groups_crud
from app.db.session import get_session
from app.models import (
    CollectorType,
    CredentialProfile,
    CredentialType,
    Device,
    DeviceCheckType,
    DeviceNeighbor,
    NetworkInterface,
    Site,
)
from app.schemas.common import Page
from app.schemas.device_group import (
    DeviceGroupCreate,
    DeviceGroupRead,
    DeviceGroupUpdate,
)
from app.schemas.interface import (
    InterfaceMetrics,
    LinkSpeedOverrideUpdate,
    NetworkInterfaceRead,
)
from app.schemas.metrics import MetricPoint
from app.schemas.v1 import (
    CollectorV1,
    DeviceMetricSeries,
    DeviceV1Create,
    DeviceV1Read,
    DeviceV1Status,
    DeviceV1Update,
    ErrorResponse,
    NeighborV1Read,
)
from app.services import prometheus

router = APIRouter(prefix="/api/v1", tags=["v1"])


_COLLECTOR_FROM_V1: dict[str, CollectorType] = {
    "generic_snmp": CollectorType.GENERIC,
    "mikrotik": CollectorType.MIKROTIK,
    "cisco": CollectorType.CISCO,
}

_COLLECTOR_TO_V1: dict[CollectorType, CollectorV1] = {
    CollectorType.GENERIC: "generic_snmp",
    CollectorType.MIKROTIK: "mikrotik",
    CollectorType.CISCO: "cisco",
}


def _collector_to_v1(value: CollectorType) -> CollectorV1:
    return _COLLECTOR_TO_V1.get(value, "generic_snmp")


def _collector_from_v1(value: str) -> CollectorType:
    try:
        return _COLLECTOR_FROM_V1[value]
    except KeyError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "collector must be generic_snmp, mikrotik, or cisco",
        ) from None


def _device_read(device: Device, parent_id: UUID | None = None) -> DeviceV1Read:
    return DeviceV1Read(
        id=device.public_id,
        site_id=device.site_id,
        name=device.name,
        ip_address=str(device.mgmt_ip),
        mac_address=str(device.mac) if device.mac is not None else None,
        collector=_collector_to_v1(device.collector),
        device_type=device.device_type,
        check_type=device.check_type,
        credential_profile_id=device.credential_profile_id,
        vendor=device.vendor,
        model=device.model,
        os_version=device.os_version,
        parent_device_id=parent_id,
        active=device.is_active,
        cpu_usage_percent=device.cpu_usage_percent,
        memory_total_bytes=device.memory_total_bytes,
        memory_used_bytes=device.memory_used_bytes,
        disk_total_bytes=device.disk_total_bytes,
        disk_used_bytes=device.disk_used_bytes,
        temperature_celsius=device.temperature_celsius,
        voltage_volts=device.voltage_volts,
        fan_speed_rpm=device.fan_speed_rpm,
        fans_ok=device.fans_ok,
        power_supplies_ok=device.power_supplies_ok,
        uptime_seconds=device.uptime_seconds,
        dhcp_lease_count=device.dhcp_lease_count,
        arp_entry_count=device.arp_entry_count,
        created_at=device.created_at,
        updated_at=device.updated_at,
    )


async def _parent_public_id(
    session: AsyncSession, device: Device
) -> UUID | None:
    if device.parent_device_id is None:
        return None
    parent = await session.scalar(
        select(Device).where(Device.id == device.parent_device_id)
    )
    return parent.public_id if parent is not None else None


async def _get_device(session: AsyncSession, public_id: UUID) -> Device | None:
    return await session.scalar(
        select(Device).where(Device.public_id == public_id)
    )


async def _check_mac(
    session: AsyncSession, mac: str | None, *, excluding: int | None = None
) -> None:
    if mac is None:
        return
    statement = select(Device.id).where(Device.mac == mac)
    if excluding is not None:
        statement = statement.where(Device.id != excluding)
    if await session.scalar(statement) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a device with this MAC address already exists",
        )


async def _resolve_parent(
    session: AsyncSession, parent_id: UUID | None, *, excluding: int | None = None
) -> int | None:
    if parent_id is None:
        return None
    parent = await _get_device(session, parent_id)
    if parent is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "parent device not found"
        )
    if excluding is not None and parent.id == excluding:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "device cannot be its own parent",
        )
    return parent.id


async def _validate_device_check(
    session: AsyncSession,
    check_type: DeviceCheckType,
    profile_id: int | None,
    collector: CollectorType,
) -> None:
    if check_type is DeviceCheckType.PING_ONLY:
        if profile_id is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "ping-only checks must not have a credential profile",
            )
        return
    if profile_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "this check type requires a credential profile",
        )
    profile = await session.get(CredentialProfile, profile_id)
    if profile is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "credential profile not found"
        )
    valid = (
        profile.credential_type
        in {CredentialType.SNMP_V2C, CredentialType.SNMP_V3}
        if check_type is DeviceCheckType.SNMP
        else profile.credential_type is CredentialType.ROUTEROS_API
        and collector is CollectorType.MIKROTIK
        if check_type is DeviceCheckType.ROUTEROS_API
        else profile.credential_type is CredentialType.CISCO_RESTCONF
        and collector is CollectorType.CISCO
    )
    if not valid:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "credential profile type does not match the device check type and collector",
        )


async def _build_device_read(
    session: AsyncSession, device: Device
) -> DeviceV1Read:
    return _device_read(device, await _parent_public_id(session, device))


@router.get("/groups", response_model=Page[DeviceGroupRead])
async def list_groups(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[DeviceGroupRead]:
    rows, total = await groups_crud.list_groups(
        session, limit=limit, offset=offset
    )
    return Page(
        items=[DeviceGroupRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/groups",
    response_model=DeviceGroupRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_group(
    payload: DeviceGroupCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceGroupRead:
    try:
        group = await groups_crud.create_group(session, payload)
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "a group with this name already exists"
        ) from None
    return DeviceGroupRead.model_validate(group)


@router.get("/groups/{group_id}", response_model=DeviceGroupRead)
async def get_group(
    group_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceGroupRead:
    group = await groups_crud.get_group(session, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "group not found")
    return DeviceGroupRead.model_validate(group)


@router.patch("/groups/{group_id}", response_model=DeviceGroupRead)
async def update_group(
    group_id: int,
    payload: DeviceGroupUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceGroupRead:
    group = await groups_crud.get_group(session, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "group not found")
    if "name" in payload.model_fields_set and payload.name is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "name may not be null"
        )
    try:
        group = await groups_crud.update_group(session, group, payload)
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "a group with this name already exists"
        ) from None
    return DeviceGroupRead.model_validate(group)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    group = await groups_crud.get_group(session, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "group not found")
    await groups_crud.delete_group(session, group)


@router.get("/devices", response_model=Page[DeviceV1Read])
async def list_devices(
    session: Annotated[AsyncSession, Depends(get_session)],
    site_id: int | None = None,
    collector: str | None = None,
    active: bool | None = None,
    vendor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[DeviceV1Read]:
    filters = []
    if site_id is not None:
        filters.append(Device.site_id == site_id)
    if collector is not None:
        filters.append(Device.collector == _collector_from_v1(collector))
    if active is not None:
        filters.append(Device.is_active.is_(active))
    if vendor is not None:
        filters.append(func.lower(Device.vendor) == vendor.lower())

    total = (
        await session.scalar(
            select(func.count()).select_from(Device).where(*filters)
        )
        or 0
    )
    rows = await session.scalars(
        select(Device)
        .where(*filters)
        .order_by(Device.name, Device.id)
        .limit(limit)
        .offset(offset)
    )
    items = [
        await _build_device_read(session, device) for device in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/devices",
    response_model=DeviceV1Read,
    status_code=status.HTTP_201_CREATED,
)
async def create_device(
    payload: DeviceV1Create,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceV1Read:
    if await session.get(Site, payload.site_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "site not found")
    await _check_mac(session, payload.mac_address)
    parent_device_id = await _resolve_parent(session, payload.parent_device_id)
    collector_type = _collector_from_v1(payload.collector)
    await _validate_device_check(
        session,
        payload.check_type,
        payload.credential_profile_id,
        collector_type,
    )
    device = Device(
        site_id=payload.site_id,
        name=payload.name,
        mgmt_ip=str(payload.ip_address),
        mac=payload.mac_address,
        collector=collector_type,
        device_type=payload.device_type,
        check_type=payload.check_type,
        credential_profile_id=payload.credential_profile_id,
        vendor=payload.vendor,
        model=payload.model,
        os_version=payload.os_version,
        parent_device_id=parent_device_id,
        is_active=payload.active,
    )
    session.add(device)
    try:
        await session.commit()
        await session.refresh(device)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "device name or MAC address already exists"
        ) from None
    return await _build_device_read(session, device)


@router.get(
    "/devices/status",
    response_model=list[DeviceV1Status],
    responses={502: {"model": ErrorResponse}},
)
async def list_device_status(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DeviceV1Status]:
    devices = await session.scalars(
        select(Device).where(Device.is_active.is_(True)).order_by(Device.name)
    )
    try:
        up = _vector_values(await prometheus.query("device_up"))
        latency = _vector_values(await prometheus.query("device_latency_ms"))
        loss = _vector_values(await prometheus.query("packet_loss_percent"))
    except prometheus.PrometheusError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Prometheus metrics are unavailable"
        ) from exc
    return [
        DeviceV1Status(
            device_id=device.public_id,
            name=device.name,
            up=None if device.name not in up else up[device.name] >= 1,
            latency_ms=latency.get(device.name),
            packet_loss_percent=loss.get(device.name),
            last_seen_at=device.last_seen_at,
        )
        for device in devices
    ]


@router.get("/devices/{device_id}", response_model=DeviceV1Read)
async def get_device(
    device_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceV1Read:
    device = await _get_device(session, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device not found")
    return await _build_device_read(session, device)


@router.patch("/devices/{device_id}", response_model=DeviceV1Read)
async def update_device(
    device_id: UUID,
    payload: DeviceV1Update,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceV1Read:
    device = await _get_device(session, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device not found")
    changes = payload.model_dump(exclude_unset=True)
    if any(
        changes.get(field) is None
        for field in (
            "site_id",
            "name",
            "ip_address",
            "collector",
            "device_type",
            "check_type",
            "active",
        )
        if field in changes
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "required device fields may not be null",
        )
    if "site_id" in changes and await session.get(Site, changes["site_id"]) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "site not found")
    mac = changes.get("mac_address", device.mac)
    await _check_mac(session, mac, excluding=device.id)
    collector_type = device.collector
    if "collector" in changes:
        collector_type = _collector_from_v1(changes["collector"])
    await _validate_device_check(
        session,
        changes.get("check_type", device.check_type),
        changes.get("credential_profile_id", device.credential_profile_id),
        collector_type,
    )
    if "parent_device_id" in changes:
        device.parent_device_id = await _resolve_parent(
            session, changes["parent_device_id"], excluding=device.id
        )
    field_map = {
        "site_id": "site_id",
        "name": "name",
        "ip_address": "mgmt_ip",
        "mac_address": "mac",
        "vendor": "vendor",
        "model": "model",
        "os_version": "os_version",
        "active": "is_active",
        "device_type": "device_type",
        "check_type": "check_type",
        "credential_profile_id": "credential_profile_id",
    }
    for source, target in field_map.items():
        if source in changes:
            value = changes[source]
            setattr(device, target, str(value) if source == "ip_address" else value)
    if "collector" in changes:
        device.collector = collector_type
    try:
        await session.commit()
        await session.refresh(device)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "device name or MAC address already exists"
        ) from None
    return await _build_device_read(session, device)


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    device = await _get_device(session, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device not found")
    await session.delete(device)
    await session.commit()


@router.get(
    "/devices/{device_id}/interfaces",
    response_model=list[NetworkInterfaceRead],
)
async def list_device_interfaces(
    device_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[NetworkInterfaceRead]:
    device = await _get_device(session, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device not found")
    rows = await session.scalars(
        select(NetworkInterface)
        .where(NetworkInterface.device_id == device.id)
        .order_by(NetworkInterface.if_index)
    )
    return [NetworkInterfaceRead.model_validate(row) for row in rows]


@router.get(
    "/devices/{device_id}/neighbors",
    response_model=list[NeighborV1Read],
)
async def list_device_neighbors(
    device_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[NeighborV1Read]:
    device = await _get_device(session, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device not found")
    rows = await session.scalars(
        select(DeviceNeighbor)
        .where(DeviceNeighbor.device_id == device.id)
        .order_by(
            DeviceNeighbor.protocol,
            DeviceNeighbor.local_interface,
            DeviceNeighbor.id,
        )
    )
    return [NeighborV1Read.model_validate(row) for row in rows]


@router.get(
    "/devices/{device_id}/interfaces/metrics",
    response_model=list[InterfaceMetrics],
    responses={502: {"model": ErrorResponse}},
)
async def get_device_interfaces_metrics(
    device_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    range_hours: int = Query(default=24, ge=24, le=720),
    step_seconds: int = Query(default=300, ge=30, le=3600),
) -> list[InterfaceMetrics]:
    if range_hours not in {24, 168, 720}:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "range_hours must be 24, 168, or 720",
        )
    device = await _get_device(session, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device not found")
    site = await session.get(Site, device.site_id)
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "site not found")
    interfaces = list(
        await session.scalars(
            select(NetworkInterface)
            .where(NetworkInterface.device_id == device.id)
            .order_by(NetworkInterface.if_index)
        )
    )
    selector = f"device={json.dumps(device.name)},site={json.dumps(site.code)}"
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
        "crc_errors_per_second": (
            f"rate(interface_crc_errors_total{{{selector}}}[{rate_window}s])"
        ),
        "in_discards_per_second": (
            f"rate(interface_in_discards_total{{{selector}}}[{rate_window}s])"
        ),
        "out_discards_per_second": (
            f"rate(interface_out_discards_total{{{selector}}}[{rate_window}s])"
        ),
        "in_utilization": f"interface_in_link_utilization_ratio{{{selector}}}",
        "out_utilization": f"interface_out_link_utilization_ratio{{{selector}}}",
        "in_utilization_percent": (
            f"interface_in_utilization_percent{{{selector}}}"
        ),
        "out_utilization_percent": (
            f"interface_out_utilization_percent{{{selector}}}"
        ),
    }
    end = datetime.now(UTC)
    start = end - timedelta(hours=range_hours)
    try:
        values = await asyncio.gather(
            *(
                prometheus.query_range(
                    query, start=start, end=end, step_seconds=step_seconds
                )
                for query in queries.values()
            )
        )
    except prometheus.PrometheusError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Prometheus metrics are unavailable"
        ) from exc
    by_interface = {
        key: _range_points_by_interface(series)
        for key, series in zip(queries, values, strict=True)
    }
    return [
        InterfaceMetrics(
            interface_id=row.id,
            interface_name=row.name,
            range_seconds=range_hours * 3600,
            step_seconds=step_seconds,
            **{
                key: by_interface[key].get(row.name, [])
                for key in queries
            },
        )
        for row in interfaces
    ]


@router.patch(
    "/devices/{device_id}/interfaces/{interface_id}",
    response_model=NetworkInterfaceRead,
)
async def update_device_interface(
    device_id: UUID,
    interface_id: int,
    payload: LinkSpeedOverrideUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NetworkInterfaceRead:
    device = await _get_device(session, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device not found")
    row = await session.scalar(
        select(NetworkInterface).where(
            NetworkInterface.id == interface_id,
            NetworkInterface.device_id == device.id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "interface not found")
    row.link_speed_override_mbps = payload.link_speed_override_mbps
    await session.commit()
    await session.refresh(row)
    return NetworkInterfaceRead.model_validate(row)


@router.get(
    "/devices/{device_id}/interfaces/{interface_id}/metrics",
    response_model=InterfaceMetrics,
    responses={502: {"model": ErrorResponse}},
)
async def get_device_interface_metrics(
    device_id: UUID,
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
    device = await _get_device(session, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device not found")
    row = await session.scalar(
        select(NetworkInterface).where(
            NetworkInterface.id == interface_id,
            NetworkInterface.device_id == device.id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "interface not found")
    site = await session.get(Site, device.site_id)
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "site not found")
    selector = (
        f"device={json.dumps(device.name)},"
        f"interface={json.dumps(row.name)},"
        f"site={json.dumps(site.code)}"
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
        "crc_errors_per_second": (
            f"rate(interface_crc_errors_total{{{selector}}}[{rate_window}s])"
        ),
        "in_discards_per_second": (
            f"rate(interface_in_discards_total{{{selector}}}[{rate_window}s])"
        ),
        "out_discards_per_second": (
            f"rate(interface_out_discards_total{{{selector}}}[{rate_window}s])"
        ),
        "in_utilization": f"interface_in_link_utilization_ratio{{{selector}}}",
        "out_utilization": f"interface_out_link_utilization_ratio{{{selector}}}",
        "in_utilization_percent": (
            f"interface_in_utilization_percent{{{selector}}}"
        ),
        "out_utilization_percent": (
            f"interface_out_utilization_percent{{{selector}}}"
        ),
    }
    end = datetime.now(UTC)
    start = end - timedelta(hours=range_hours)
    try:
        values = await asyncio.gather(
            *(
                prometheus.query_range(
                    query, start=start, end=end, step_seconds=step_seconds
                )
                for query in queries.values()
            )
        )
    except prometheus.PrometheusError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Prometheus metrics are unavailable"
        ) from exc
    result = {
        key: _range_points(series) for key, series in zip(queries, values, strict=True)
    }
    return InterfaceMetrics(
        interface_id=row.id,
        interface_name=row.name,
        range_seconds=range_hours * 3600,
        step_seconds=step_seconds,
        **result,
    )


def _vector_values(result: list[dict[str, Any]]) -> dict[str, float]:
    values: dict[str, float] = {}
    for series in result:
        metric = series.get("metric")
        sample = series.get("value")
        if not isinstance(metric, dict) or not isinstance(sample, list):
            continue
        name = metric.get("device")
        if not isinstance(name, str) or len(sample) < 2:
            continue
        try:
            value = float(sample[1])
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            values[name] = value
    return values


def _range_points(
    result: list[dict[str, Any]], *, multiplier: float = 1.0
) -> list[MetricPoint]:
    points: list[MetricPoint] = []
    for series in result:
        samples = series.get("values")
        if not isinstance(samples, list):
            continue
        for sample in samples:
            if not isinstance(sample, list) or len(sample) < 2:
                continue
            try:
                timestamp = float(sample[0])
                value = float(sample[1]) * multiplier
            except (TypeError, ValueError):
                continue
            if math.isfinite(timestamp) and math.isfinite(value):
                points.append(MetricPoint(t=timestamp, value=value))
    points.sort(key=lambda point: point.t)
    return points


def _range_points_by_interface(
    result: list[dict[str, Any]],
) -> dict[str, list[MetricPoint]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for series in result:
        metric = series.get("metric")
        interface = metric.get("interface") if isinstance(metric, dict) else None
        if isinstance(interface, str):
            grouped.setdefault(interface, []).append(series)
    return {
        interface: _range_points(series)
        for interface, series in grouped.items()
    }


@router.get(
    "/devices/{device_id}/metrics",
    response_model=DeviceMetricSeries,
    responses={502: {"model": ErrorResponse}},
)
async def get_device_metrics(
    device_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    range_minutes: int = Query(default=60, ge=5, le=1440),
    step_seconds: int = Query(default=30, ge=5, le=3600),
) -> DeviceMetricSeries:
    device = await _get_device(session, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device not found")
    end = datetime.now(UTC)
    start = end - timedelta(minutes=range_minutes)
    selector = f"device={json.dumps(device.name)}"
    try:
        latency, packet_loss = await asyncio.gather(
            prometheus.query_range(
                f"ping_latency_seconds{{{selector}}}",
                start=start,
                end=end,
                step_seconds=step_seconds,
            ),
            prometheus.query_range(
                f"packet_loss_percent{{{selector}}}",
                start=start,
                end=end,
                step_seconds=step_seconds,
            ),
        )
    except prometheus.PrometheusError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Prometheus metrics are unavailable"
        ) from exc
    return DeviceMetricSeries(
        device_id=device.public_id,
        latency=_range_points(latency, multiplier=1000),
        packet_loss_percent=_range_points(packet_loss),
    )
