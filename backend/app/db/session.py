"""Async engine and session factory."""

import os
from collections.abc import AsyncIterator

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Load the repository .env (if any); real environment variables win. Inside
# Docker the file is absent and DATABASE_URL comes from Compose.
load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://mgkk:local-dev-password@localhost:5433/mgkk",
)

engine: AsyncEngine = create_async_engine(DATABASE_URL, pool_pre_ping=True)

# expire_on_commit=False avoids implicit lazy loads after commit, which fail
# in async code.
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request."""
    async with SessionLocal() as session:
        yield session
