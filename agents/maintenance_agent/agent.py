"""Deterministic Maintenance Agent exposed through the ADK A2A adapter."""

from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent, InvocationContext
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.events import Event
from google.genai import types

MAX_REQUEST_LENGTH = 2_000
EQUIPMENT_TERMS = (
    "エアコン",
    "空調",
    "冷房",
    "暖房",
    "設備",
    "air conditioner",
    "air conditioning",
)
FAULT_TERMS = (
    "故障",
    "壊",
    "動かない",
    "効かない",
    "不具合",
    "修理",
    "broken",
    "malfunction",
    "not working",
)

REPAIR_RESPONSE = "修理担当者が夕食後に伺います。"
EMPTY_REQUEST_RESPONSE = "故障した設備と症状を教えてください。"
UNSUPPORTED_REQUEST_RESPONSE = "設備故障の依頼を確認できません。設備名と症状を教えてください。"
LONG_REQUEST_RESPONSE = "依頼文が長すぎます。設備名と症状を短くお知らせください。"


def response_for_request(request: str) -> str:
    """Return a fixed maintenance response without echoing guest input."""
    normalized = request.strip().casefold()
    if not normalized:
        return EMPTY_REQUEST_RESPONSE
    if len(normalized) > MAX_REQUEST_LENGTH:
        return LONG_REQUEST_RESPONSE
    if any(term in normalized for term in EQUIPMENT_TERMS) and any(
        term in normalized for term in FAULT_TERMS
    ):
        return REPAIR_RESPONSE
    return UNSUPPORTED_REQUEST_RESPONSE


def _request_text(content: types.Content | None) -> str:
    if content is None or not content.parts:
        return ""
    return "\n".join(part.text for part in content.parts if part.text)


class MaintenanceAgent(BaseAgent):
    """Handle equipment failure inquiries using deterministic demo logic."""

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


root_agent = MaintenanceAgent(
    name="maintenance_agent",
    description=(
        "設備故障の問い合わせを担当します。エアコンなどの故障を確認し、"
        "デモでは修理担当者が夕食後に伺うと回答します。"
    ),
)

# ADK generates the Agent Card and A2A Task endpoint from the agent metadata.
# Keep this port aligned with the uvicorn command used to start the service.
a2a_app = to_a2a(root_agent, host="localhost", port=8001)
