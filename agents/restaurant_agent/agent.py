"""Deterministic Restaurant Agent with in-memory approval state."""

import asyncio
import json
import secrets
from collections.abc import AsyncGenerator
from typing import Any

from google.adk.agents import BaseAgent, InvocationContext
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.events import Event
from google.genai import types

from agents.restaurant_agent.consultation import consultation_service

MAX_REQUEST_LENGTH = 2_000
# 2000文字の相談文と200文字の会話IDをJSON escapeしても受付ける。
MAX_ENVELOPE_LENGTH = 14_000
CURRENT_RESERVATION_TIME = "19:00"
PROPOSED_RESERVATION_TIME = "20:00"


class RestaurantReservationStore:
    """Own a demo reservation and pending proposals for this process only."""

    def __init__(self) -> None:
        self._reservation_time = CURRENT_RESERVATION_TIME
        self._pending_proposals: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        action = request.get("action")
        async with self._lock:
            if action == "get_status" and set(request) == {"action"}:
                return {
                    "status": "ok",
                    "reservation_time": self._reservation_time,
                }
            if action == "propose_change":
                return self._propose_change(request)
            if action == "approve_change":
                return self._approve_change(request)
            if action == "reject_change":
                return self._reject_change(request)
        return {"status": "invalid_request", "message": "依頼形式を確認してください。"}

    def _propose_change(self, request: dict[str, Any]) -> dict[str, Any]:
        if set(request) != {"action", "requested_time"}:
            return self._invalid_request()
        requested_time = request.get("requested_time")
        if (
            not isinstance(requested_time, str)
            or requested_time != PROPOSED_RESERVATION_TIME
        ):
            return self._invalid_request()
        if self._reservation_time == requested_time:
            return {
                "status": "unchanged",
                "reservation_time": self._reservation_time,
                "message": "予約はすでに20時です。",
            }

        proposal_id = secrets.token_urlsafe(16)
        self._pending_proposals[proposal_id] = requested_time
        return {
            "status": "proposed",
            "proposal_id": proposal_id,
            "current_time": self._reservation_time,
            "proposed_time": requested_time,
            "approval_required": True,
            "message": "20時への変更が可能です。承認前の予約時刻は変更していません。",
        }

    def _approve_change(self, request: dict[str, Any]) -> dict[str, Any]:
        proposal_id = request.get("proposal_id")
        if set(request) != {"action", "proposal_id"} or not self._valid_proposal_id(
            proposal_id
        ):
            return self._invalid_request()
        proposed_time = self._pending_proposals.pop(proposal_id, None)
        if proposed_time is None:
            return {"status": "not_found", "message": "有効な変更案が見つかりません。"}
        self._reservation_time = proposed_time
        return {
            "status": "approved",
            "reservation_time": self._reservation_time,
            "message": "予約を20時に変更しました。",
        }

    def _reject_change(self, request: dict[str, Any]) -> dict[str, Any]:
        proposal_id = request.get("proposal_id")
        if set(request) != {"action", "proposal_id"} or not self._valid_proposal_id(
            proposal_id
        ):
            return self._invalid_request()
        if self._pending_proposals.pop(proposal_id, None) is None:
            return {"status": "not_found", "message": "有効な変更案が見つかりません。"}
        return {
            "status": "rejected",
            "reservation_time": self._reservation_time,
            "message": "変更案を取り下げました。予約時刻は変更していません。",
        }

    @staticmethod
    def _valid_proposal_id(proposal_id: Any) -> bool:
        return isinstance(proposal_id, str) and 1 <= len(proposal_id) <= 64

    @staticmethod
    def _invalid_request() -> dict[str, Any]:
        return {"status": "invalid_request", "message": "依頼形式を確認してください。"}


async def response_for_request(
    request_text: str, store: RestaurantReservationStore
) -> str:
    """Validate a JSON A2A command and return the store's JSON response."""
    if len(request_text) > MAX_ENVELOPE_LENGTH:
        result = {"status": "invalid_request", "message": "依頼文が長すぎます。"}
    else:
        try:
            payload = json.loads(request_text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            if "version" in payload:
                result = await consultation_service.handle(payload)
            elif len(request_text) > MAX_REQUEST_LENGTH:
                result = {"status": "invalid_request", "message": "依頼文が長すぎます。"}
            else:
                result = await store.handle(payload)
        else:
            result = {
                "status": "invalid_request",
                "message": "依頼形式を確認してください。",
            }
    return json.dumps(result, ensure_ascii=False)


def _request_text(content: types.Content | None) -> str:
    if content is None or not content.parts:
        return ""
    return "\n".join(part.text for part in content.parts if part.text)


reservation_store = RestaurantReservationStore()


class RestaurantAgent(BaseAgent):
    """Propose and apply restaurant reservation changes on explicit commands."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        response = await response_for_request(
            _request_text(ctx.user_content), reservation_store
        )
        yield Event(
            author=self.name,
            branch=ctx.branch,
            invocation_id=ctx.invocation_id,
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=response)],
            ),
        )


root_agent = RestaurantAgent(
    name="restaurant_agent",
    description=(
        "館内レストランの空席検索、予約照合、新規予約と変更の相談・提案を担当します。"
        "希望日時・人数・席種に合う候補を確認します。提案だけでは予約は確定しません。"
    ),
)

# ADK generates the Agent Card and A2A Task endpoint from the agent metadata.
# Keep this port aligned with the uvicorn command used to start the service.
a2a_app = to_a2a(root_agent, host="localhost", port=8003)
