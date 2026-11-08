from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, Timestamps

CODE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]*$"


class SiteBase(BaseModel):
    code: str = Field(min_length=1, max_length=32, pattern=CODE_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    address: str | None = None
    timezone: str = Field(default="UTC", max_length=64)
    notes: str | None = None


class SiteCreate(SiteBase):
    pass


class SiteUpdate(BaseModel):
    """All fields optional; apply with model_dump(exclude_unset=True)."""

    code: str | None = Field(default=None, min_length=1, max_length=32, pattern=CODE_PATTERN)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    address: str | None = None
    timezone: str | None = Field(default=None, max_length=64)
    notes: str | None = None


class SiteRead(SiteBase, Timestamps):
    id: int


class SiteRef(ORMModel):
    """Compact form for embedding in other responses."""

    id: int
    code: str
    name: str
