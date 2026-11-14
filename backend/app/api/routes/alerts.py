"""Alert history, Alertmanager webhook, silences, maintenance, and live events."""

import asyncio
import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_session
from app.models import (
    AlertEvent,
    Device,
    DeviceGroup,
    MaintenanceWindow,
    Site,
    SyslogEvent,
    device_group_members,
)
from app.schemas.alerts import (
    AlertAcknowledge,
    AlertEventRead,
    AlertmanagerAlert,
    AlertmanagerWebhook,
    MaintenanceWindowCreate,
    MaintenanceWindowRead,
    MaintenanceWindowUpdate,
    SilenceCreate,
    SyslogEventRead,
    WebhookResult,
)
from app.schemas.common import Page
from app.services import alertmanager, events

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["alerts"])


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_dt(value: datetime | None, fallback: datetime) -> datetime:
    if value is None or value.year <= 1:
        return fallback
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _resolve_device(
    session: AsyncSession, labels: dict[str, str]
) -> Device | None:
    device: Device | None = None
    public_id = labels.get("device_id")
    if public_id:
        try:
            device = await session.scalar(
                select(Device)
                .where(Device.public_id == UUID(public_id))
                .options(selectinload(Device.site))
            )
        except (ValueError, TypeError):
            device = None
    if device is None and labels.get("device"):
        device = await session.scalar(
            select(Device)
            .where(Device.name == labels["device"])
            .options(selectinload(Device.site))
        )
    return device


async def _maintenance_applies(
    session: AsyncSession, device: Device | None, now: datetime
) -> bool:
    if device is None:
        return False
    windows = await session.scalars(
        select(MaintenanceWindow).where(
            MaintenanceWindow.starts_at <= now,
            MaintenanceWindow.ends_at > now,
            MaintenanceWindow.suppress_notifications.is_(True),
        )
    )
    for window in windows:
        if window.scope_type == "device" and window.device_id == device.id:
            return True
        if window.scope_type == "site" and window.site_id == device.site_id:
            return True
        if window.scope_type == "group" and window.group_id is not None:
            member = await session.scalar(
                select(device_group_members.c.device_id).where(
                    device_group_members.c.group_id == window.group_id,
                    device_group_members.c.device_id == device.id,
                )
            )
            if member is not None:
                return True
    return False


def _alert_fingerprint(alert: AlertmanagerAlert) -> str:
    if alert.fingerprint:
        return alert.fingerprint
    canonical = json.dumps(alert.labels, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _upsert_alert(
    session: AsyncSession, alert: AlertmanagerAlert, now: datetime
) -> tuple[AlertEvent, bool]:
    fingerprint = _alert_fingerprint(alert)
    starts_at = _parse_dt(alert.starts_at, now)
    ends_at = _parse_dt(alert.ends_at, now) if alert.status == "resolved" else None
    resolved = alert.status == "resolved"
    device = await _resolve_device(session, alert.labels)
    suppressed = False if resolved else await _maintenance_applies(session, device, now)
    raw = json.loads(alert.model_dump_json(by_alias=True))
    values = {
        "alertname": alert.labels.get("alertname", "UnnamedAlert"),
        "device_id": device.id if device is not None else None,
        "device_name": alert.labels.get("device")
        or (device.name if device is not None else None),
        "site": alert.labels.get("site")
        or (device.site.code if device is not None and device.site else None),
        "severity": alert.labels.get("severity", "warning"),
        "summary": alert.annotations.get("summary"),
        "description": alert.annotations.get("description"),
        "labels": alert.labels,
        "annotations": alert.annotations,
        "raw": raw,
        "last_received_at": now,
    }

    if resolved:
        event = await session.scalar(
            select(AlertEvent)
            .where(AlertEvent.fingerprint == fingerprint)
            .order_by(AlertEvent.starts_at.desc())
            .limit(1)
        )
        if event is None:
            event = AlertEvent(
                fingerprint=fingerprint,
                starts_at=starts_at,
                ends_at=ends_at or now,
                status="resolved",
                **values,
            )
            session.add(event)
        else:
            suppressed = event.suppressed
            for key, value in values.items():
                setattr(event, key, value)
            event.status = "resolved"
            event.ends_at = ends_at or now
        return event, suppressed

    event = await session.scalar(
        select(AlertEvent).where(
            AlertEvent.fingerprint == fingerprint,
            AlertEvent.starts_at == starts_at,
        )
    )
    if event is None:
        event = AlertEvent(
            fingerprint=fingerprint,
            starts_at=starts_at,
            status="firing",
            suppressed=suppressed,
            **values,
        )
        session.add(event)
    else:
        for key, value in values.items():
            setattr(event, key, value)
        event.status = "firing"
        event.ends_at = None
        event.suppressed = suppressed
    return event, suppressed


@router.post("/alerts/webhook", response_model=WebhookResult)
async def alertmanager_webhook(
    payload: AlertmanagerWebhook,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WebhookResult:
    now = _now()
    processed = 0
    suppressed_count = 0
    pending_events: list[dict[str, Any]] = []
    for alert in payload.alerts:
        event, suppressed = await _upsert_alert(session, alert, now)
        processed += 1
        if suppressed:
            suppressed_count += 1
            continue
        await session.flush()
        pending_events.append(
            {
                "type": "alert_resolved"
                if event.status == "resolved"
                else "alert_fired",
                "alert_id": str(event.public_id),
                "alertname": event.alertname,
                "device": event.device_name,
                "device_id": event.labels.get("device_id"),
                "site": event.site,
                "severity": event.severity,
                "status": event.status,
                "summary": event.summary,
            }
        )
    await session.commit()
    for item in pending_events:
        event_type = str(item.pop("type"))
        await events.publish_event(event_type, item)
    return WebhookResult(processed=processed, suppressed=suppressed_count)


@router.get("/alerts", response_model=Page[AlertEventRead])
async def list_alerts(
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: str | None = Query(default=None, alias="status"),
    severity: str | None = None,
    site: str | None = None,
    device_id: UUID | None = None,
    acknowledged: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[AlertEventRead]:
    filters: list[Any] = []
    if status_filter:
        filters.append(AlertEvent.status == status_filter)
    if severity:
        filters.append(AlertEvent.severity == severity)
    if site:
        filters.append(AlertEvent.site == site)
    if acknowledged is not None:
        filters.append(
            AlertEvent.acknowledged_at.is_not(None)
            if acknowledged
            else AlertEvent.acknowledged_at.is_(None)
        )
    if device_id is not None:
        device = await session.scalar(
            select(Device).where(Device.public_id == device_id)
        )
        filters.append(AlertEvent.device_id == (device.id if device else -1))
    total = (
        await session.scalar(
            select(func.count()).select_from(AlertEvent).where(*filters)
        )
        or 0
    )
    rows = await session.scalars(
        select(AlertEvent)
        .where(*filters)
        .order_by(AlertEvent.starts_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return Page(
        items=[AlertEventRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/alerts/{alert_id}/ack", response_model=AlertEventRead)
async def acknowledge_alert(
    alert_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    payload: AlertAcknowledge | None = None,
) -> AlertEventRead:
    event = await session.scalar(
        select(AlertEvent).where(AlertEvent.public_id == alert_id)
    )
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "alert not found")
    event.acknowledged_at = _now()
    event.acknowledged_by = (payload.acknowledged_by if payload else None) or "operator"
    await session.commit()
    await session.refresh(event)
    return AlertEventRead.model_validate(event)


async def _resolve_target(
    session: AsyncSession, scope: str, target_id: UUID
) -> tuple[int | None, int | None, int | None, Any]:
    if scope == "device":
        target = await session.scalar(
            select(Device).where(Device.public_id == target_id)
        )
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "device not found")
        return target.id, None, None, target
    if scope == "group":
        target = await session.scalar(
            select(DeviceGroup)
            .where(DeviceGroup.public_id == target_id)
            .options(selectinload(DeviceGroup.devices))
        )
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "group not found")
        return None, target.id, None, target
    target = await session.scalar(select(Site).where(Site.public_id == target_id))
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "site not found")
    return None, None, target.id, target


def _silence_matchers(scope: str, target: Any) -> list[list[dict[str, Any]]]:
    if scope == "device":
        return [[{"name": "device", "value": target.name}]]
    if scope == "site":
        return [[{"name": "site", "value": target.code}]]
    return [
        [{"name": "device", "value": device.name}]
        for device in getattr(target, "devices", [])
    ]


async def _create_silences(
    window: MaintenanceWindow, scope: str, target: Any
) -> list[str]:
    if not window.suppress_notifications:
        return []
    silence_ids: list[str] = []
    for matchers in _silence_matchers(scope, target):
        try:
            silence_ids.append(
                await alertmanager.create_silence(
                    matchers,
                    window.starts_at,
                    window.ends_at,
                    created_by=window.created_by or "mgkk",
                    comment=window.name,
                )
            )
        except alertmanager.AlertmanagerError as exc:
            logger.warning(
                "Could not create Alertmanager silence for maintenance %s: %s",
                window.name,
                exc,
            )
    return silence_ids


async def _expire_silences(window: MaintenanceWindow) -> None:
    for silence_id in (window.silence_ids or "").split(","):
        if not silence_id:
            continue
        try:
            await alertmanager.expire_silence(silence_id)
        except alertmanager.AlertmanagerError as exc:
            logger.warning("Could not expire silence %s: %s", silence_id, exc)


def _window_read(
    window: MaintenanceWindow,
    *,
    device_id: UUID | None = None,
    group_id: UUID | None = None,
    site_id: UUID | None = None,
) -> MaintenanceWindowRead:
    return MaintenanceWindowRead(
        id=window.public_id,
        name=window.name,
        description=window.description,
        scope_type=window.scope_type,
        device_id=device_id,
        group_id=group_id,
        site_id=site_id,
        starts_at=window.starts_at,
        ends_at=window.ends_at,
        suppress_notifications=window.suppress_notifications,
        silence_ids=[item for item in (window.silence_ids or "").split(",") if item],
        created_by=window.created_by,
        created_at=window.created_at,
        updated_at=window.updated_at,
    )


async def _window_public_ids(
    session: AsyncSession, window: MaintenanceWindow
) -> dict[str, UUID | None]:
    result: dict[str, UUID | None] = {
        "device_id": None,
        "group_id": None,
        "site_id": None,
    }
    if window.device_id is not None:
        device = await session.get(Device, window.device_id)
        result["device_id"] = device.public_id if device else None
    if window.group_id is not None:
        group = await session.get(DeviceGroup, window.group_id)
        result["group_id"] = group.public_id if group else None
    if window.site_id is not None:
        site = await session.get(Site, window.site_id)
        result["site_id"] = site.public_id if site else None
    return result


async def _read_window(
    session: AsyncSession, window: MaintenanceWindow
) -> MaintenanceWindowRead:
    ids = await _window_public_ids(session, window)
    return _window_read(window, **ids)


@router.get("/maintenance-windows", response_model=Page[MaintenanceWindowRead])
async def list_maintenance_windows(
    session: Annotated[AsyncSession, Depends(get_session)],
    active_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[MaintenanceWindowRead]:
    now = _now()
    filters: list[Any] = []
    if active_only:
        filters.extend(
            [
                MaintenanceWindow.starts_at <= now,
                MaintenanceWindow.ends_at > now,
            ]
        )
    total = (
        await session.scalar(
            select(func.count()).select_from(MaintenanceWindow).where(*filters)
        )
        or 0
    )
    rows = await session.scalars(
        select(MaintenanceWindow)
        .where(*filters)
        .order_by(MaintenanceWindow.starts_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return Page(
        items=[await _read_window(session, row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/maintenance-windows",
    response_model=MaintenanceWindowRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_maintenance_window(
    payload: MaintenanceWindowCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MaintenanceWindowRead:
    device_id, group_id, site_id, target = await _resolve_target(
        session, payload.scope_type, payload.target_id
    )
    window = MaintenanceWindow(
        name=payload.name,
        description=payload.description,
        scope_type=payload.scope_type,
        device_id=device_id,
        group_id=group_id,
        site_id=site_id,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        suppress_notifications=payload.suppress_notifications,
        created_by=payload.created_by,
    )
    silences = await _create_silences(window, payload.scope_type, target)
    window.silence_ids = ",".join(silences) or None
    session.add(window)
    await session.commit()
    return await _read_window(session, window)


@router.patch("/maintenance-windows/{window_id}", response_model=MaintenanceWindowRead)
async def update_maintenance_window(
    window_id: UUID,
    payload: MaintenanceWindowUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MaintenanceWindowRead:
    window = await session.scalar(
        select(MaintenanceWindow).where(MaintenanceWindow.public_id == window_id)
    )
    if window is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "maintenance window not found")
    changes = payload.model_dump(exclude_unset=True)
    for key in ("name", "starts_at", "ends_at", "suppress_notifications"):
        if changes.get(key) is None:
            changes.pop(key, None)
    starts_at = changes.get("starts_at", window.starts_at)
    ends_at = changes.get("ends_at", window.ends_at)
    if ends_at <= starts_at:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "maintenance window must end after it starts",
        )
    target = None
    if (
        "starts_at" in changes
        or "ends_at" in changes
        or "suppress_notifications" in changes
    ):
        _, _, _, target = await _resolve_target(
            session,
            window.scope_type,
            await _target_public_id(session, window),
        )
        await _expire_silences(window)
    for key, value in changes.items():
        setattr(window, key, value)
    if target is not None:
        silences = await _create_silences(window, window.scope_type, target)
        window.silence_ids = ",".join(silences) or None
    await session.commit()
    await session.refresh(window)
    return await _read_window(session, window)


async def _target_public_id(session: AsyncSession, window: MaintenanceWindow) -> UUID:
    ids = await _window_public_ids(session, window)
    target_id = ids.get("device_id") or ids.get("group_id") or ids.get("site_id")
    if target_id is None:  # pragma: no cover - FK constraints prevent this
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "maintenance window target is missing",
        )
    return target_id


@router.delete(
    "/maintenance-windows/{window_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_maintenance_window(
    window_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    window = await session.scalar(
        select(MaintenanceWindow).where(MaintenanceWindow.public_id == window_id)
    )
    if window is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "maintenance window not found")
    await _expire_silences(window)
    await session.delete(window)
    await session.commit()


@router.get("/silences")
async def get_silences() -> list[dict[str, Any]]:
    try:
        return await alertmanager.list_silences()
    except alertmanager.AlertmanagerError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.post("/silences", status_code=status.HTTP_201_CREATED)
async def create_silence(payload: SilenceCreate) -> dict[str, str]:
    try:
        silence_id = await alertmanager.create_silence(
            [matcher.model_dump(by_alias=True) for matcher in payload.matchers],
            payload.starts_at,
            payload.ends_at,
            created_by=payload.created_by,
            comment=payload.comment,
        )
    except alertmanager.AlertmanagerError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {"silenceID": silence_id}


@router.delete("/silences/{silence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_silence(silence_id: str) -> None:
    try:
        await alertmanager.expire_silence(silence_id)
    except alertmanager.AlertmanagerError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("/syslog", response_model=Page[SyslogEventRead])
async def list_syslog_events(
    session: Annotated[AsyncSession, Depends(get_session)],
    device_id: UUID | None = None,
    event_type: str | None = None,
    min_severity: int = Query(default=0, ge=0, le=7),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[SyslogEventRead]:
    filters: list[Any] = [SyslogEvent.severity >= min_severity]
    if event_type:
        filters.append(SyslogEvent.event_type == event_type)
    if device_id is not None:
        device = await session.scalar(
            select(Device).where(Device.public_id == device_id)
        )
        filters.append(SyslogEvent.device_id == (device.id if device else -1))
    total = (
        await session.scalar(
            select(func.count()).select_from(SyslogEvent).where(*filters)
        )
        or 0
    )
    rows = await session.scalars(
        select(SyslogEvent)
        .where(*filters)
        .order_by(SyslogEvent.occurred_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return Page(
        items=[SyslogEventRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def _ws_matches(event: dict[str, Any], site: str | None, device: str | None) -> bool:
    if site and event.get("site") != site:
        return False
    return not (device and device not in {event.get("device"), event.get("device_id")})


@router.websocket("/ws/events")
async def websocket_events(
    websocket: WebSocket,
    token: str | None = None,
    site: str | None = None,
    device: str | None = None,
) -> None:
    expected = os.getenv("WS_AUTH_TOKEN")
    if expected:
        header = websocket.headers.get("authorization", "")
        provided = token or (header[7:] if header.startswith("Bearer ") else None)
        if provided != expected:
            await websocket.close(code=4401, reason="invalid event token")
            return

    await websocket.accept()
    redis = await events.get_redis()
    if redis is None:
        await websocket.send_json(
            {"type": "error", "message": "event bus is not configured"}
        )
        await websocket.close(code=1011)
        return

    pubsub = redis.pubsub()
    await pubsub.subscribe(events.EVENTS_CHANNEL)
    last_heartbeat = 0.0
    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message is not None:
                payload = json.loads(message["data"])
                if _ws_matches(payload, site, device):
                    await websocket.send_json(payload)
            now = asyncio.get_running_loop().time()
            if now - last_heartbeat >= 25:
                await websocket.send_json(
                    {"type": "heartbeat", "timestamp": _now().isoformat()}
                )
                last_heartbeat = now
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await pubsub.unsubscribe(events.EVENTS_CHANNEL)
        await pubsub.aclose()  # type: ignore[no-untyped-call]
