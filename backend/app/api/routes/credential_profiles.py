"""Encrypted shared credential profile routes."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import CredentialProfile, CredentialType, Device
from app.schemas import (
    CredentialProfileCreate,
    CredentialProfileRead,
    CredentialProfileUpdate,
)
from app.services.credentials import (
    CredentialConfigurationError,
    encrypt_secret,
)

router = APIRouter(prefix="/credential-profiles", tags=["credential profiles"])


def _default_port(credential_type: CredentialType) -> int:
    return 161 if credential_type == CredentialType.SNMP_V2C else 443


def _validate_profile_fields(
    credential_type: CredentialType, username: str | None
) -> None:
    if credential_type == CredentialType.SNMP_V2C and username is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "SNMP v2c profiles do not use a username",
        )
    if credential_type == CredentialType.ROUTEROS_API and not username:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "RouterOS API profiles require a username",
        )


@router.get("", response_model=list[CredentialProfileRead])
async def list_credential_profiles(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[CredentialProfileRead]:
    rows = await session.scalars(
        select(CredentialProfile).order_by(CredentialProfile.name)
    )
    return [CredentialProfileRead.model_validate(row) for row in rows]


@router.post(
    "",
    response_model=CredentialProfileRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_credential_profile(
    payload: CredentialProfileCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CredentialProfileRead:
    try:
        ciphertext = encrypt_secret(payload.secret)
    except CredentialConfigurationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    profile = CredentialProfile(
        name=payload.name,
        credential_type=payload.credential_type,
        username=payload.username,
        secret_ciphertext=ciphertext,
        port=payload.port or _default_port(payload.credential_type),
        verify_tls=payload.verify_tls,
    )
    session.add(profile)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a credential profile with this name already exists",
        ) from None
    await session.refresh(profile)
    return CredentialProfileRead.model_validate(profile)


@router.patch("/{profile_id}", response_model=CredentialProfileRead)
async def update_credential_profile(
    profile_id: int,
    payload: CredentialProfileUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CredentialProfileRead:
    profile = await session.get(CredentialProfile, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "credential profile not found")

    changes: dict[str, Any] = payload.model_dump(exclude_unset=True)
    secret_was_sent = "secret" in changes
    secret = changes.pop("secret", None)
    if secret_was_sent and secret is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "secret may not be null"
        )
    if any(
        changes.get(field) is None
        for field in ("name", "credential_type", "verify_tls")
        if field in changes
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "name, credential_type, and verify_tls may not be null",
        )
    credential_type = changes.get("credential_type", profile.credential_type)
    username = changes.get("username", profile.username)
    _validate_profile_fields(credential_type, username)
    if credential_type != profile.credential_type:
        used = await session.scalar(
            select(func.count()).select_from(Device).where(
                Device.credential_profile_id == profile_id
            )
        )
        if used:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "cannot change the type of an assigned credential profile",
            )

    for field, value in changes.items():
        if value is None and field not in {"port"}:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"field may not be null: {field}",
            )
        setattr(profile, field, value)
    if "port" in changes and changes["port"] is None:
        profile.port = _default_port(credential_type)
    if secret is not None:
        try:
            profile.secret_ciphertext = encrypt_secret(secret)
        except CredentialConfigurationError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)
            ) from exc

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a credential profile with this name already exists",
        ) from None
    await session.refresh(profile)
    return CredentialProfileRead.model_validate(profile)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential_profile(
    profile_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    profile = await session.get(CredentialProfile, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "credential profile not found")
    used = await session.scalar(
        select(func.count()).select_from(Device).where(
            Device.credential_profile_id == profile_id
        )
    )
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "credential profile is assigned to one or more devices",
        )
    await session.delete(profile)
    await session.commit()
