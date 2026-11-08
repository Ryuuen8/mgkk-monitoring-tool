from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, Timestamps


class DeviceGroupBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None


class DeviceGroupCreate(DeviceGroupBase):
    pass


class DeviceGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None


class DeviceGroupRead(DeviceGroupBase, Timestamps):
    id: int


class DeviceGroupRef(ORMModel):
    id: int
    name: str


class GroupMembersUpdate(BaseModel):
    """Body for adding or removing devices from a group."""

    device_ids: list[int] = Field(min_length=1)
