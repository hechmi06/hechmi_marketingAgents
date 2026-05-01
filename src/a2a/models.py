"""
Modèles du protocole A2A (Agent-to-Agent).
Spec: https://google.github.io/A2A/
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ── Parts ─────────────────────────────────────────────────────────

class TextPart(BaseModel):
    type: str = "text"
    text: str


class DataPart(BaseModel):
    type: str = "data"
    data: dict[str, Any]


Part = TextPart | DataPart


# ── Messages ──────────────────────────────────────────────────────

class Message(BaseModel):
    role: str  # "user" | "agent"
    parts: list[Part]


# ── Task ──────────────────────────────────────────────────────────

class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class Artifact(BaseModel):
    name: str | None = None
    parts: list[Part]


class Task(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    state: TaskState = TaskState.SUBMITTED
    messages: list[Message] = []
    artifacts: list[Artifact] = []
    metadata: dict[str, Any] = {}


# ── Agent Card ────────────────────────────────────────────────────

class Skill(BaseModel):
    id: str
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict, alias="inputSchema")

    model_config = {"populate_by_name": True}


class AgentCard(BaseModel):
    name: str
    description: str
    url: str
    version: str = "1.0.0"
    capabilities: list[str] = []
    skills: list[Skill] = []


# ── Requêtes / Réponses ──────────────────────────────────────────

class TaskSendRequest(BaseModel):
    message: Message
    metadata: dict[str, Any] = {}


class TaskSendResponse(BaseModel):
    task: Task
