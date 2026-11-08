"""DB fixtures. Needs a PostgreSQL database; skipped if unreachable.

Set TEST_DATABASE_URL (or put it in the repository .env), e.g.
    postgresql+asyncpg://mgkk:local-dev-password@localhost:5433/mgkk_test
"""

import os

import app.models
import pytest
import pytest_asyncio
from app.db.base import Base
from app.db.session import get_session
from app.main import app
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv()

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://mgkk:local-dev-password@localhost:5433/mgkk_test",
)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except (OSError, SQLAlchemyError) as exc:  # pragma: no cover
        await engine.dispose()
        pytest.skip(f"PostgreSQL not available: {exc}")

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session):
    """HTTP client whose routes share the test fixture's database session."""

    async def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.pop(get_session, None)
