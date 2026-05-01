"""
Client A2A — utilisé par l'orchestrateur pour communiquer avec les agents.

Flux : découverte (Agent Card) → envoi de Task → lecture du résultat.
"""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger

from src.a2a.models import (
    AgentCard,
    DataPart,
    Message,
    Task,
    TaskSendRequest,
    TaskSendResponse,
    TextPart,
)


class A2AClient:
    """Client HTTP pour interagir avec un agent A2A distant."""

    def __init__(self, base_url: str, timeout: float = 600.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ── Découverte ────────────────────────────────────────────

    async def get_agent_card(self) -> AgentCard:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self.base_url}/.well-known/agent.json")
            resp.raise_for_status()
            return AgentCard(**resp.json())

    # ── Envoi d'une tâche ─────────────────────────────────────

    async def send_task(
        self,
        data: dict[str, Any] | None = None,
        text: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        parts = []
        if text:
            parts.append(TextPart(text=text))
        if data:
            parts.append(DataPart(data=data))

        if not parts:
            parts.append(TextPart(text="run"))

        request = TaskSendRequest(
            message=Message(role="user", parts=parts),
            metadata=metadata or {},
        )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/tasks/send",
                json=request.model_dump(),
            )
            resp.raise_for_status()
            task_resp = TaskSendResponse(**resp.json())
            return task_resp.task

    # ── Consultation ──────────────────────────────────────────

    async def get_task(self, task_id: str) -> Task:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self.base_url}/tasks/{task_id}")
            resp.raise_for_status()
            return Task(**resp.json())

    # ── Annulation ────────────────────────────────────────────

    async def cancel_task(self, task_id: str) -> Task:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{self.base_url}/tasks/{task_id}/cancel")
            resp.raise_for_status()
            return Task(**resp.json())

    # ── Helper ────────────────────────────────────────────────

    def extract_data(self, task: Task) -> dict[str, Any]:
        """Extrait le premier DataPart des artifacts de la tâche."""
        for artifact in task.artifacts:
            for part in artifact.parts:
                if isinstance(part, DataPart):
                    return part.data
                if isinstance(part, dict) and part.get("type") == "data":
                    return part.get("data", {})
        return {}

    def extract_text(self, task: Task) -> str:
        """Extrait le premier TextPart des messages agent."""
        for msg in reversed(task.messages):
            if msg.role == "agent":
                for part in msg.parts:
                    if isinstance(part, TextPart):
                        return part.text
                    if isinstance(part, dict) and part.get("type") == "text":
                        return part.get("text", "")
        return ""
