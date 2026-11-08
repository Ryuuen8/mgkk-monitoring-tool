"""Site CRUD routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import sites as crud
from app.db.session import get_session
from app.schemas import Page, SiteCreate, SiteRead, SiteUpdate

router = APIRouter(prefix="/sites", tags=["sites"])

SITE_NOT_FOUND = "site not found"
SITE_CODE_CONFLICT = "a site with this code already exists"
SITE_IN_USE = "site still has devices; move or delete them first"

# Fields that map to NOT NULL columns; an explicit null in PATCH is a client
# error, not a conflict with an existing row.
REQUIRED_FIELDS = ("code", "name", "timezone")


def _reject_nulls(changes: dict[str, object]) -> None:
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


@router.get("", response_model=Page[SiteRead])
async def list_sites(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[SiteRead]:
    rows, total = await crud.list_sites(session, limit=limit, offset=offset)
    return Page(
        items=[SiteRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{site_id}", response_model=SiteRead)
async def get_site(
    site_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SiteRead:
    site = await crud.get_site(session, site_id)
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, SITE_NOT_FOUND)
    return SiteRead.model_validate(site)


@router.post("", response_model=SiteRead, status_code=status.HTTP_201_CREATED)
async def create_site(
    payload: SiteCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SiteRead:
    try:
        site = await crud.create_site(session, payload)
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, SITE_CODE_CONFLICT
        ) from None
    return SiteRead.model_validate(site)


@router.patch("/{site_id}", response_model=SiteRead)
async def update_site(
    site_id: int,
    payload: SiteUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SiteRead:
    site = await crud.get_site(session, site_id)
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, SITE_NOT_FOUND)
    _reject_nulls(payload.model_dump(exclude_unset=True))
    try:
        site = await crud.update_site(session, site, payload)
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, SITE_CODE_CONFLICT
        ) from None
    return SiteRead.model_validate(site)


@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(
    site_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    site = await crud.get_site(session, site_id)
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, SITE_NOT_FOUND)
    try:
        await crud.delete_site(session, site)
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, SITE_IN_USE) from None
