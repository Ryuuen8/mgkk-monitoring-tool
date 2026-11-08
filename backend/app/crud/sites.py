"""Site data access."""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Site
from app.schemas import SiteCreate, SiteUpdate


async def list_sites(
    session: AsyncSession, *, limit: int = 50, offset: int = 0
) -> tuple[list[Site], int]:
    """Return one page of sites plus the total row count."""
    total = await session.scalar(select(func.count()).select_from(Site)) or 0
    rows = await session.scalars(
        select(Site).order_by(Site.id).limit(limit).offset(offset)
    )
    return list(rows), total


async def get_site(session: AsyncSession, site_id: int) -> Site | None:
    return await session.get(Site, site_id)


async def get_site_by_code(session: AsyncSession, code: str) -> Site | None:
    return await session.scalar(select(Site).where(Site.code == code))


async def create_site(session: AsyncSession, payload: SiteCreate) -> Site:
    site = Site(**payload.model_dump())
    session.add(site)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise
    await session.refresh(site)
    return site


async def update_site(
    session: AsyncSession, site: Site, payload: SiteUpdate
) -> Site:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(site, field, value)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise
    await session.refresh(site)
    return site


async def delete_site(session: AsyncSession, site: Site) -> None:
    await session.delete(site)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise
