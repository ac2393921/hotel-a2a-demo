"""Serve the guest chat UI and route every guest turn through Front Desk."""

import asyncio
import logging
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
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

    for message in reversed(messages):
        if message["role"] == "assistant" and (
            "変更案" in message["text"] or "予約はまだ変更していません" in message["text"]
        ):
            return {"text": message["text"]}
    return {"text": "レストランの変更案が承認待ちです。"}


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


@app.get("/api/sessions/{session_id}")
async def get_conversation(session_id: str) -> dict:
    session = await _get_session(session_id)
    messages = _conversation(session)
    return {
        "session_id": session.id,
        "messages": messages,
        "pending_proposal": _pending_proposal(session, messages),
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
        }
