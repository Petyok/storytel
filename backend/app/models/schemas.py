from typing import Any

from pydantic import BaseModel, Field


class PlayerFlag(BaseModel):
    model_config = {"extra": "allow"}


class NPCState(BaseModel):
    name: str = ""
    trust: int = 0
    hidden_intent: str = ""


class PlayerView(BaseModel):
    hp: int = 100
    gold: int = 0
    status: str = "steady"
    inventory: list[str] = Field(default_factory=list)
    flags: dict[str, Any] = Field(default_factory=dict)
    name: str = "Wanderer"


class WorldView(BaseModel):
    location: str = "unknown"
    danger_level: int = 1
    time: str = "night"
    secrets: list[str] = Field(default_factory=list)
    npcs: list[NPCState] = Field(default_factory=list)
    ascii_map: str = ""
    turn: int = 0


class QuestsView(BaseModel):
    active: list[dict[str, Any]] = Field(default_factory=list)
    completed: list[dict[str, Any]] = Field(default_factory=list)


class UnifiedStateView(BaseModel):
    player: PlayerView
    world: WorldView
    quests: QuestsView


class SessionGetResponse(BaseModel):
    session_id: str
    state: UnifiedStateView
    last_scene: str
    choices: list[str]
    notices: list[str] = Field(default_factory=list)


class ActionRequest(BaseModel):
    choice: str = Field(..., min_length=1, max_length=2000)


class ActionResponse(BaseModel):
    session_id: str
    scene: str
    choices: list[str]
    notices: list[str] = Field(default_factory=list)
    state: UnifiedStateView
    llm_ok: bool = True
    effects_applied: list[str] = Field(default_factory=list)


class SessionsListResponse(BaseModel):
    sessions: list[str]


class SessionPlayerSetup(BaseModel):
    name: str = Field(default="Wanderer", max_length=80)
    backstory: str = Field(default="", max_length=2000)


class SessionWorldSetup(BaseModel):
    location: str = Field(default="Ashen Gate", max_length=120)
    premise: str = Field(default="", max_length=2000)


class CreateSessionRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64)
    overwrite: bool = False
    language: str = Field(default="en", max_length=16)
    player: SessionPlayerSetup | None = None
    world: SessionWorldSetup | None = None
