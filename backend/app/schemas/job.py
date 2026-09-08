from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

JobTitle = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=200,
    ),
]

JobDescription = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=20_000,
    ),
]


class JobCreate(BaseModel):
    title: JobTitle
    description: JobDescription


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: str
    title: str
    description: str
    created_at: datetime


class JobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: str
    title: str
    created_at: datetime


class JobListRead(BaseModel):
    items: list[JobSummary]
    limit: int
    offset: int
    has_more: bool
