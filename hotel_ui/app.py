"""Serve the guest chat UI and route every guest turn through Front Desk."""

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google.adk.agents.remote_a2a_agent import (
    A2A_METADATA_PREFIX,
    AGENT_CARD_WELL_KNOWN_PATH,
)
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field, field_validator

from agents.front_desk_agent.agent import (
    PENDING_RESTAURANT_PROPOSAL_KEY,
    root_agent,
)

APP_NAME = "front_desk_agent"
USER_ID = "local_guest"
STATIC_DIR = Path(__file__).parent / "static"
logger = logging.getLogger(__name__)
AGENTS = (
    {
        "id": "maintenance_agent",
        "label": "Maintenance Agent",
        "env": "MAINTENANCE_AGENT_BASE_URL",
        "port": 8001,
    },
    {
        "id": "housekeeping_agent",
        "label": "Housekeeping Agent",
        "env": "HOUSEKEEPING_AGENT_BASE_URL",
        "port": 8002,
    },
    {
        "id": "restaurant_agent",
        "label": "Restaurant Agent",
        "env": "RESTAURANT_AGENT_BASE_URL",
        "port": 8003,
    },
)

session_service = InMemorySessionService()
runner = Runner(
    app_name=APP_NAME,
    agent=root_agent,
    session_service=session_service,
)
session_locks: dict[str, asyncio.Lock] = {}

app = FastAPI(title="Hotel A2A Guest UI")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class GuestMessage(BaseModel):
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def reject_whitespace_only(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("メッセージを入力してください")
        return value.strip()


def _event_text(event) -> str:
    if not event.content or not event.content.parts:
        return ""
    return "\n".join(
        part.text
        for part in event.content.parts
        if part.text and not part.thought
    ).strip()


def _conversation(session) -> list[dict[str, str]]:
    messages = []
    for event in session.events:
        if event.author == "user":
            role: Literal["user", "assistant"] = "user"
        elif event.author == root_agent.name and event.content:
            role = "assistant"
        else:
            continue

        text = _event_text(event)
        if text:
            messages.append({"role": role, "text": text})
    return messages


def _pending_proposal(session, messages: list[dict[str, str]]) -> dict[str, str] | None:
    if not session.state.get(PENDING_RESTAURANT_PROPOSAL_KEY):
        return None

    for event in reversed(session.events):
        if event.author != "restaurant_agent":
            continue
        text = _event_text(event)
        if "変更案" in text or "予約はまだ変更していません" in text:
            return {"text": text}

    for message in reversed(messages):
        if message["role"] != "assistant":
            continue
        for line in message["text"].splitlines():
            if line.startswith("- Restaurant Agent ") and "変更案" in line:
                return {"text": line.rsplit(": ", maxsplit=1)[-1]}
    return {"text": "レストランの変更案が承認待ちです。"}


def _task_state(response: object) -> str | None:
    if not isinstance(response, dict):
        return None
    status = response.get("status")
    if not isinstance(status, dict):
        return None
    state = status.get("state")
    if not isinstance(state, str):
        return None
    normalized = state.casefold().replace("_", "-")
    if normalized.endswith("completed"):
        return "完了"
    if normalized.endswith("failed"):
        return "失敗"
    if normalized.endswith("canceled"):
        return "キャンセル"
    if normalized.endswith("rejected"):
        return "拒否"
    if normalized.endswith("input-required"):
        return "追加情報待ち"
    if normalized.endswith("working"):
        return "対応中"
    if normalized.endswith("submitted"):
        return "受付済み"
    return None


def _stored_task_state(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if value in {
        "受付済み",
        "対応中",
        "実行中",
        "追加情報待ち",
        "完了",
        "失敗",
        "キャンセル",
        "拒否",
    }:
        return "対応中" if value == "実行中" else value
    return "失敗" if value == "failed" else None


def _task_timeline(session) -> list[dict[str, object]]:
    latest_user_event = next(
        (event for event in reversed(session.events) if event.author == "user"),
        None,
    )
    if latest_user_event is None:
        return []

    tasks: dict[tuple[str, str], dict[str, object]] = {}
    for event in session.events:
        if event.invocation_id != latest_user_event.invocation_id:
            continue
        agent = next((item for item in AGENTS if item["id"] == event.author), None)
        if agent is None:
            continue

        metadata = event.custom_metadata or {}
        task_id = metadata.get(f"{A2A_METADATA_PREFIX}task_id")
        response = metadata.get(f"{A2A_METADATA_PREFIX}response")
        state = "失敗" if event.error_message else _task_state(response)
        if state is None:
            state = _stored_task_state(metadata.get("task_status"))
        if state is None and not _event_text(event):
            continue

        key_id = task_id if isinstance(task_id, str) else event.invocation_id
        key = (agent["id"], key_id)
        task = tasks.setdefault(
            key,
            {
                "agent_id": agent["id"],
                "agent_name": agent["label"],
                "task_id": task_id if isinstance(task_id, str) else None,
                "events": [],
            },
        )
        timestamp = event.timestamp
        if isinstance(timestamp, (int, float)):
            timestamp = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
        timeline_event = {
            "status": state or "応答受信",
            "timestamp": timestamp if isinstance(timestamp, str) else None,
            "text": _event_text(event)
            or ("部署AgentとのA2A通信に失敗しました。" if state == "失敗" else ""),
        }
        events = task["events"]
        if not events or events[-1] != timeline_event:
            events.append(timeline_event)

    return list(tasks.values())


def _agent_card_url(agent: dict[str, object]) -> str:
    base_url = os.getenv(str(agent["env"]), f"http://localhost:{agent['port']}")
    return f"{base_url.rstrip('/')}{AGENT_CARD_WELL_KNOWN_PATH}"


async def _fetch_agent_card(
    client: httpx.AsyncClient, agent: dict[str, object]
) -> dict[str, object]:
    card: dict[str, object] = {
        "id": agent["id"],
        "label": agent["label"],
        "available": False,
        "description": "Agent Cardを取得できません。Agentサービスの起動状態を確認してください。",
        "skills": [],
    }
    try:
        response = await client.get(_agent_card_url(agent))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return card
        skills = payload.get("skills", [])
        card.update(
            {
                "available": True,
                "name": (
                    payload["name"][:120]
                    if isinstance(payload.get("name"), str)
                    else agent["label"]
                ),
                "description": (
                    payload["description"][:1000]
                    if isinstance(payload.get("description"), str)
                    else ""
                ),
                "skills": [
                    {
                        "name": skill.get("name", "")[:120],
                        "description": skill.get("description", "")[:500],
                    }
                    for skill in skills[:10]
                    if isinstance(skill, dict)
                    and isinstance(skill.get("name", ""), str)
                    and isinstance(skill.get("description", ""), str)
                ]
                if isinstance(skills, list)
                else [],
            }
        )
    except (httpx.HTTPError, ValueError) as error:
        logger.info(
            "Agent Card unavailable for %s: %s",
            agent["id"],
            type(error).__name__,
        )
    return card


async def _get_session(session_id: str):
    session = await session_service.get_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=session_id,
    )
    if session is None:
        raise HTTPException(
            status_code=404,
            detail="会話が見つかりません。新しい会話を開始してください。",
        )
    return session


@app.get("/", include_in_schema=False)
async def guest_home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/sessions")
async def create_session() -> dict[str, str]:
    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
    )
    session_locks[session.id] = asyncio.Lock()
    return {"session_id": session.id}


@app.get("/api/agents")
async def get_agents() -> dict[str, list[dict[str, object]]]:
    timeout = httpx.Timeout(2.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        cards = await asyncio.gather(
            *(_fetch_agent_card(client, agent) for agent in AGENTS)
        )
    return {"agents": cards}


@app.get("/api/sessions/{session_id}")
async def get_conversation(session_id: str) -> dict:
    session = await _get_session(session_id)
    messages = _conversation(session)
    return {
        "session_id": session.id,
        "messages": messages,
        "pending_proposal": _pending_proposal(session, messages),
        "tasks": _task_timeline(session),
    }


@app.post("/api/sessions/{session_id}/messages")
async def send_message(session_id: str, message: GuestMessage) -> dict:
    lock = session_locks.get(session_id)
    if lock is None:
        await _get_session(session_id)
        raise HTTPException(status_code=404, detail="会話が見つかりません。")
    if lock.locked():
        raise HTTPException(status_code=409, detail="前のメッセージを処理中です。")

    async with lock:
        await _get_session(session_id)
        reply = ""
        try:
            async for event in runner.run_async(
                user_id=USER_ID,
                session_id=session_id,
                new_message=types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=message.text)],
                ),
            ):
                if event.author == root_agent.name and event.content:
                    reply = _event_text(event)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error("Front Desk execution failed: %s", type(error).__name__)
            raise HTTPException(
                status_code=502,
                detail="Front Desk Agentから応答を受け取れませんでした。",
            ) from error

        if not reply:
            raise HTTPException(
                status_code=502,
                detail="Front Desk Agentから応答を受け取れませんでした。",
            )

        session = await _get_session(session_id)
        messages = _conversation(session)
        return {
            "reply": reply,
            "pending_proposal": _pending_proposal(session, messages),
            "tasks": _task_timeline(session),
        }
