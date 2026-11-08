from datetime import datetime
from enum import StrEnum
from typing import Any, Self
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

FACT_KIND = "fact"


class Visibility(StrEnum):
    DM = "dm"
    ALL = "all"
    PLAYER = "player"


class FactSource(StrEnum):
    GENERATION = "generation"
    BACKSTORY = "backstory"
    GAME = "game"


class VisibilityError(ValueError):
    pass


class Provenance(BaseModel):
    step: str
    model: str
    attempt_id: int | None = None


class Record(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    kind: str
    visibility: Visibility
    player_id: str | None = None
    version: int = 0
    provenance: Provenance | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def _player_id_matches_visibility(self) -> Self:
        if (self.visibility is Visibility.PLAYER) != (self.player_id is not None):
            raise ValueError("player_id is required for and only for visibility 'player'")
        return self


class CampaignInfo(BaseModel):
    id: str
    title: str
    created_at: datetime
    is_test: bool
    status: str
