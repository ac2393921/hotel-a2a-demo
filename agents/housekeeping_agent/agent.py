"""Deterministic Housekeeping Agent exposed through the ADK A2A adapter."""

from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent, InvocationContext
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.events import Event
from google.genai import types

MAX_REQUEST_LENGTH = 2_000
ROOM_CHANGE_TERMS = (
    "代替部屋",
    "別の部屋",
    "別室",
    "部屋を変",
    "部屋の変更",
    "空室",
    "room change",
    "alternative room",
    "replacement room",
)

ROOM_AVAILABLE_RESPONSE = "代替のお部屋をご用意できます。"
EMPTY_REQUEST_RESPONSE = "ご希望の客室対応を教えてください。"
UNSUPPORTED_REQUEST_RESPONSE = "客室変更の依頼を確認できません。ご希望を教えてください。"
LONG_REQUEST_RESPONSE = "依頼文が長すぎます。ご希望を短くお知らせください。"


def response_for_request(request: str) -> str:
    """Return a fixed room-availability response without echoing guest input."""
    normalized = request.strip().casefold()
    if not normalized:
        return EMPTY_REQUEST_RESPONSE
    if len(normalized) > MAX_REQUEST_LENGTH:
        return LONG_REQUEST_RESPONSE
    if any(term in normalized for term in ROOM_CHANGE_TERMS):
        return ROOM_AVAILABLE_RESPONSE
    return UNSUPPORTED_REQUEST_RESPONSE


def _request_text(content: types.Content | None) -> str:
    if content is None or not content.parts:
        return ""
    return "\n".join(part.text for part in content.parts if part.text)


class HousekeepingAgent(BaseAgent):
    """Handle alternative-room inquiries using deterministic demo logic."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        response = response_for_request(_request_text(ctx.user_content))
        yield Event(
            author=self.name,
            branch=ctx.branch,
            invocation_id=ctx.invocation_id,
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=response)],
            ),
        )


root_agent = HousekeepingAgent(
    name="housekeeping_agent",
    description=(
        "代替客室や客室変更の照会を担当します。デモでは代替のお部屋を"
        "ご用意できると回答します。"
    ),
)

# ADK generates the Agent Card and A2A Task endpoint from the agent metadata.
# Keep this port aligned with the uvicorn command used to start the service.
a2a_app = to_a2a(root_agent, host="localhost", port=8002)
