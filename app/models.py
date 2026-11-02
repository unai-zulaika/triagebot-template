from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator

ALLOWED_CATEGORIES = {"bug", "feature_request", "question", "urgent"}
ALLOWED_PRIORITIES = {"P1", "P2", "P3"}
ALLOWED_STATUSES = {"open", "in_progress", "resolved", "closed"}

Category = Literal["bug", "feature_request", "question", "urgent"]
Priority = Literal["P1", "P2", "P3"]
Status = Literal["open", "in_progress", "resolved", "closed"]

TitleStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
DescriptionStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)
]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]


class TicketCreate(BaseModel):
    title: TitleStr
    description: DescriptionStr


class Ticket(BaseModel):
    id: int
    title: TitleStr
    description: DescriptionStr
    category: Category
    priority: Priority
    tags: list[Tag] = []
    status: Status
    created_at: datetime
    updated_at: datetime

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        return [tag.lower() for tag in value][:5]


class TicketUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Status | None = None
    priority: Priority | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "TicketUpdate":
        if self.status is None and self.priority is None:
            raise ValueError("status or priority must be provided")
        return self
