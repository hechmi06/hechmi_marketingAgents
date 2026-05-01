"""
Serveur A2A générique — fabrique une app FastAPI conforme au protocole A2A.

Chaque agent instancie `create_a2a_app(card, handler)` avec :
  - card : AgentCard décrivant l'agent
  - handler : async fn(task: Task) -> Task  (logique métier)
"""

from __future__ import annotations

from typing import Callable, Awaitable

from fastapi import FastAPI, HTTPException
from loguru import logger

from src.a2a.models import (
    AgentCard,
    Artifact,
    Message,
    Task,
    TaskSendRequest,
    TaskSendResponse,
    TaskState,
)

TaskHandler = Callable[[Task], Awaitable[Task]]


def create_a2a_app(card: AgentCard, handler: TaskHandler) -> FastAPI:
    """Crée une application FastAPI exposant les endpoints A2A."""

    app = FastAPI(title=f"A2A — {card.name}", version=card.version)

    # Stockage en mémoire des tasks (suffisant pour un prototype)
    _tasks: dict[str, Task] = {}

    # ── Découverte ────────────────────────────────────────────

    @app.get("/.well-known/agent.json")
    def agent_card():
        return card.model_dump(by_alias=True)

    # ── Envoi d'une tâche ─────────────────────────────────────

    @app.post("/tasks/send", response_model=TaskSendResponse)
    async def tasks_send(req: TaskSendRequest):
        task = Task(
            messages=[req.message],
            metadata=req.metadata,
        )
        _tasks[task.id] = task

        logger.info(f"[A2A:{card.name}] Task {task.id} → WORKING")
        task.state = TaskState.WORKING

        try:
            task = await handler(task)
            if task.state == TaskState.WORKING:
                task.state = TaskState.COMPLETED
            logger.info(f"[A2A:{card.name}] Task {task.id} → {task.state.value}")
        except Exception as e:
            task.state = TaskState.FAILED
            task.messages.append(
                Message(role="agent", parts=[{"type": "text", "text": str(e)}])
            )
            logger.error(f"[A2A:{card.name}] Task {task.id} FAILED: {e}")

        _tasks[task.id] = task
        return TaskSendResponse(task=task)

    # ── Consultation ──────────────────────────────────────────

    @app.get("/tasks/{task_id}")
    def tasks_get(task_id: str):
        task = _tasks.get(task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        return task.model_dump()

    # ── Annulation ────────────────────────────────────────────

    @app.post("/tasks/{task_id}/cancel")
    def tasks_cancel(task_id: str):
        task = _tasks.get(task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        task.state = TaskState.CANCELED
        return task.model_dump()

    # ── Health (bonus) ────────────────────────────────────────

    @app.get("/health")
    def health():
        return {"status": "ok", "agent": card.name, "protocol": "a2a"}

    return app
