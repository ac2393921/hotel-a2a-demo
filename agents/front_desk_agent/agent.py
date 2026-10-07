"""Front Desk hub that routes validated intents to independent A2A services."""

import asyncio
import json
import os
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from google.adk.agents import BaseAgent, InvocationContext, ParallelAgent
from google.adk.agents.remote_a2a_agent import (
    AGENT_CARD_WELL_KNOWN_PATH,
    A2A_METADATA_PREFIX,
    RemoteA2aAgent,
)
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.events import Event, EventActions
from google.genai import types
from pydantic import ValidationError

from agents.front_desk_agent.intent import (
    IntentExtractionResult,
    intent_agent,
    validate_intent_output,
)

PROPOSED_RESTAURANT_TIME = "20:00"
PENDING_RESTAURANT_PROPOSAL_KEY = "front_desk_pending_restaurant_proposal_id"
A2A_DEBUG_TRACE_METADATA_KEY = "hotel_a2a_debug_trace"


@dataclass(frozen=True)
class DepartmentCall:
    name: str
    display_name: str
    description: str
    agent_card: str
    request_text: str


def _agent_card_url(env_name: str, port: int) -> str:
    base_url = os.getenv(env_name, f"http://localhost:{port}").rstrip("/")
    return f"{base_url}{AGENT_CARD_WELL_KNOWN_PATH}"


def build_department_calls(
    result: IntentExtractionResult,
) -> list[DepartmentCall]:
    """Create A2A requests only for departments in the validated intent."""
    if result.decision != "dispatch":
        return []

    calls: list[DepartmentCall] = []
    for request in result.requests:
        if request.department == "maintenance_agent":
            calls.append(
                DepartmentCall(
                    name=request.department,
                    description="設備故障の問い合わせを担当するMaintenance Agent",
                    display_name="Maintenance Agent",
                    agent_card=_agent_card_url(
                        "MAINTENANCE_AGENT_BASE_URL", 8001
                    ),
                    request_text=request.details,
                )
            )
        elif request.department == "housekeeping_agent":
            calls.append(
                DepartmentCall(
                    name=request.department,
                    description="代替部屋の問い合わせを担当するHousekeeping Agent",
                    display_name="Housekeeping Agent",
                    agent_card=_agent_card_url(
                        "HOUSEKEEPING_AGENT_BASE_URL", 8002
                    ),
                    request_text=request.details,
                )
            )
        elif request.department == "restaurant_agent":
            calls.append(
                DepartmentCall(
                    name=request.department,
                    description="予約変更案を担当するRestaurant Agent",
                    display_name="Restaurant Agent",
                    agent_card=_agent_card_url(
                        "RESTAURANT_AGENT_BASE_URL", 8003
                    ),
                    request_text=json.dumps(
                        {
                            "action": "propose_change",
                            "requested_time": request.requested_time
                            or PROPOSED_RESTAURANT_TIME,
                        },
                        ensure_ascii=False,
                    ),
                )
            )
    return calls


def build_approval_call(decision: str, proposal_id: str) -> DepartmentCall:
    """Create a Restaurant A2A command for an explicit guest decision."""
    action = {"approve": "approve_change", "reject": "reject_change"}.get(decision)
    if action is None:
        raise ValueError("承認または拒否の決定が必要です")
    return DepartmentCall(
        name="restaurant_agent",
        display_name="Restaurant Agent",
        description="ゲストの判断を予約変更案へ反映するRestaurant Agent",
        agent_card=_agent_card_url("RESTAURANT_AGENT_BASE_URL", 8003),
        request_text=json.dumps(
            {"action": action, "proposal_id": proposal_id}, ensure_ascii=False
        ),
    )


def _request_context(request_text: str):
    """Keep each department request limited to its own A2A message."""

    def build_context(
        _ctx: InvocationContext,
        _agent_name: str,
        part_converter: Any,
    ) -> tuple[list[Any], None]:
        part = part_converter(types.Part.from_text(text=request_text))
        return ([part] if part is not None else []), None

    return build_context


def _create_remote_agent(call: DepartmentCall) -> RemoteA2aAgent:
    return RemoteA2aAgent(
        name=call.name,
        description=call.description,
        agent_card=call.agent_card,
        context_builder=_request_context(call.request_text),
    )


class _DepartmentFailureBoundary(BaseAgent):
    """Turn one remote-service exception into an isolated department failure."""

    department_name: str
    remote_agent: Any

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        try:
            async for event in self.remote_agent.run_async(ctx):
                yield event
        except asyncio.CancelledError:
            raise
        except Exception:
            yield Event(
                author=self.department_name,
                invocation_id=ctx.invocation_id,
                branch=ctx.branch,
                error_message="部署AgentとのA2A通信に失敗しました。",
                custom_metadata={"task_status": "failed"},
            )


def _text_from_content(content) -> str:
    return "\n".join(p.text for p in content.parts or [] if p.text) if content else ""


def _text_from_event(event: Event) -> str:
    if not event.content or not event.content.parts:
        return ""
    return "\n".join(
        part.text
        for part in event.content.parts
        if part.text and not part.thought
    )


def _task_status(event: Event) -> str | None:
    response = (event.custom_metadata or {}).get(
        f"{A2A_METADATA_PREFIX}response"
    )
    if not isinstance(response, dict):
        return None
    status = response.get("status")
    if not isinstance(status, dict):
        return None
    state = status.get("state")
    if not isinstance(state, str):
        return None
    normalized = state.casefold()
    if "completed" in normalized:
        return "完了"
    if "failed" in normalized or "canceled" in normalized:
        return "失敗"
    if "working" in normalized or "submitted" in normalized:
        return "実行中"
    return None


def _response_summary(
    calls: list[DepartmentCall],
    statuses: dict[str, str],
    responses: dict[str, list[str]],
    task_ids: dict[str, str],
) -> str:
    lines = ["部署Agentからの回答:"]
    for call in calls:
        status = statuses.get(call.name, "失敗")
        answer = "\n".join(responses.get(call.name, [])) or (
            "回答を受け取れませんでした。"
        )
        task_id = task_ids.get(call.name)
        task_text = f"（Task: {task_id}）" if task_id else ""
        lines.append(f"- {call.display_name} [{status}]{task_text}: {answer}")
    return "\n".join(lines)


class FrontDeskCoordinator(BaseAgent):
    """Extract an intent, call only its departments in parallel, and summarize."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        from agents.front_desk_agent.restaurant_flow import consultation_call, decision_call, safe_trace
        command = ctx.session.state.pop("restaurant_structured_decision", None)
        if command is not None:
            call = decision_call(ctx.session.id, command)
            if call is None:
                yield self._final_event(ctx, "有効な対象提案がありません。現在の提案を確認してください。")
                return
            calls = [call]
        else:
            ctx.session.state["restaurant_v2_mode"] = "yes" if ctx.session.state.get("restaurant_v2_enabled") else "no"
            pending_proposal_id = ctx.session.state.get(PENDING_RESTAURANT_PROPOSAL_KEY)
            ctx.session.state["restaurant_change_pending"] = (
                "yes" if pending_proposal_id else "no"
            )
            raw_intent: str | None = None
            async for event in intent_agent.run_async(ctx):
                yield event
                if event.author == intent_agent.name and event.is_final_response():
                    raw_intent = _text_from_event(event)

            if not raw_intent:
                yield self._final_event(
                    ctx,
                    "ご依頼を整理できませんでした。内容をもう一度お知らせください。",
                )
                return

            try:
                intent = validate_intent_output(raw_intent)
            except ValidationError:
                if ctx.session.state.get("restaurant_v2_active"):
                    # 分類の生成失敗でも、相談中の部署へ公開A2Aで確認する。
                    # 不正な出力を承認・拒否や別部署の操作に解釈しない。
                    intent = IntentExtractionResult(decision="clarify", response_message="予約条件を確認します。")
                else:
                    yield self._final_event(
                        ctx,
                        "ご依頼を正しく整理できませんでした。対象の内容をもう一度お知らせください。",
                    )
                    return

            if intent.decision in {"approve", "reject"}:
                if not isinstance(pending_proposal_id, str) or not pending_proposal_id:
                    yield self._final_event(
                        ctx,
                        "有効な変更案が見つかりません。現在の予約変更案を確認してください。",
                    )
                    return
                if ctx.session.state.get("restaurant_v2_active"):
                    yield self._final_event(ctx, "予約の確定・拒否は画面の承認・拒否ボタンから操作してください。")
                    return
                calls = [build_approval_call(intent.decision, pending_proposal_id)]
            elif intent.decision == "clarify" and ctx.session.state.get("restaurant_v2_active"):
                calls = [consultation_call(ctx.session.id, _text_from_content(ctx.user_content), ctx.session.state)]
            elif intent.decision != "dispatch":
                yield self._final_event(
                    ctx,
                    intent.response_message or "ご依頼の内容をもう少し詳しく教えてください。",
                )
                return

            else:
                calls = build_department_calls(intent)
                if any(r.operation == "consult_restaurant" for r in intent.requests) or (
                    ctx.session.state.get("restaurant_v2_enabled") and any(r.department == "restaurant_agent" for r in intent.requests)):
                    calls = [c for c in calls if c.name != "restaurant_agent"]
                    calls.append(consultation_call(ctx.session.id, _text_from_content(ctx.user_content), ctx.session.state))
                    ctx.session.state["restaurant_v2_active"] = True
            if not calls:
                yield self._final_event(ctx, "ご依頼に対応する部署を選べませんでした。")
                return

        remote_agents = [_create_remote_agent(call) for call in calls]
        department_agents = [
            _DepartmentFailureBoundary(
                name=f"{call.name}_failure_boundary",
                description=f"{call.display_name}のA2Aエラーを隔離します。",
                department_name=call.name,
                remote_agent=remote_agent,
            )
            for call, remote_agent in zip(calls, remote_agents, strict=True)
        ]
        parallel = ParallelAgent(
            name="parallel_department_dispatch",
            description="選択した部署Agentへ独立した依頼を同時に送ります。",
            sub_agents=department_agents,
        )
        reported_failures = set()
        statuses = {call.name: "実行中" for call in calls}
        responses: dict[str, list[str]] = {call.name: [] for call in calls}
        task_ids: dict[str, str] = {}
        for call in calls:
            yield Event(
                author=self.name,
                invocation_id=ctx.invocation_id,
                branch=ctx.branch,
                custom_metadata={
                    A2A_DEBUG_TRACE_METADATA_KEY: {
                        "kind": "request_sent",
                        "agent_id": call.name,
                        "agent_name": call.display_name,
                        "direction": f"Front Desk → {call.display_name}",
                        "payload": safe_trace(call),
                    }
                },
            )
        try:
            async for event in parallel.run_async(ctx):
                if event.author in statuses:
                    if event.error_message:
                        statuses[event.author] = "失敗"
                        reported_failures.add(event.author)
                        task_id = (event.custom_metadata or {}).get(
                            f"{A2A_METADATA_PREFIX}task_id"
                        )
                        custom_metadata = {"task_status": "failed"}
                        if isinstance(task_id, str):
                            custom_metadata[f"{A2A_METADATA_PREFIX}task_id"] = task_id
                            task_ids[event.author] = task_id
                        yield Event(
                            author=event.author,
                            invocation_id=ctx.invocation_id,
                            branch=event.branch,
                            error_message="部署AgentとのA2A通信に失敗しました。",
                            custom_metadata=custom_metadata,
                        )
                        continue

                    task_id = (event.custom_metadata or {}).get(
                        f"{A2A_METADATA_PREFIX}task_id"
                    )
                    if isinstance(task_id, str):
                        task_ids[event.author] = task_id
                    status = _task_status(event)
                    if status:
                        statuses[event.author] = status
                    response_text = _text_from_event(event)
                    if event.author == "restaurant_agent":
                        event = event.model_copy(update={"custom_metadata": {
                            k:v for k,v in (event.custom_metadata or {}).items()
                            if k in {f"{A2A_METADATA_PREFIX}task_id", "task_status"}}})
                    if event.author == "restaurant_agent" and response_text:
                        response_text, state_delta = self._handle_restaurant_response(
                            ctx, response_text
                        )
                        if response_text != _text_from_event(event):
                            custom_metadata = {
                                key: value
                                for key, value in (event.custom_metadata or {}).items()
                                if key in {f"{A2A_METADATA_PREFIX}task_id", "task_status"}
                            }
                            if status:
                                custom_metadata["task_status"] = status
                            event = event.model_copy(
                                update={
                                    "content": types.Content(
                                        role="model",
                                        parts=[
                                            types.Part.from_text(text=response_text)
                                        ],
                                    ),
                                    "custom_metadata": custom_metadata,
                                    "actions": EventActions(state_delta=state_delta),
                                }
                            )
                    if response_text and response_text not in responses[event.author]:
                        responses[event.author].append(response_text)
                yield event
        finally:
            await asyncio.gather(
                *(agent.cleanup() for agent in remote_agents),
                return_exceptions=True,
            )

        for call in calls:
            if statuses[call.name] == "実行中":
                statuses[call.name] = "完了" if responses[call.name] else "失敗"
            final_metadata = {"task_status": statuses[call.name]}
            task_id = task_ids.get(call.name)
            if task_id:
                final_metadata[f"{A2A_METADATA_PREFIX}task_id"] = task_id
            yield Event(
                author=call.name,
                invocation_id=ctx.invocation_id,
                branch=ctx.branch,
                custom_metadata=final_metadata,
                error_message=(
                    "部署AgentとのA2A通信に失敗しました。"
                    if statuses[call.name] == "失敗" and call.name not in reported_failures
                    else None
                ),
            )
        yield self._final_event(
            ctx,
            _response_summary(calls, statuses, responses, task_ids),
        )

    @staticmethod
    def _handle_restaurant_response(
        ctx: InvocationContext, response_text: str
    ) -> tuple[str, dict[str, str]]:
        try:
            response = json.loads(response_text)
        except json.JSONDecodeError:
            return response_text, {}
        if not isinstance(response, dict):
            return response_text, {}

        status = response.get("status")
        message = response.get("message")
        if status == "proposed" and isinstance(response.get("approval_token"), str):
            from agents.front_desk_agent.restaurant_flow import credentials
            proposal_id = response.get("proposal_id")
            summary = response.get("summary")
            if not isinstance(proposal_id, str) or not isinstance(summary, str):
                return "予約提案を確認できませんでした。", {}
            credentials[ctx.session.id] = (proposal_id, response["approval_token"])
            ctx.session.state[PENDING_RESTAURANT_PROPOSAL_KEY] = proposal_id
            ctx.session.state["restaurant_proposal_summary"] = summary
            ctx.session.state["restaurant_v2_active"] = True
            return summary + "画面の承認ボタンで確定できます。", {
                PENDING_RESTAURANT_PROPOSAL_KEY: proposal_id, "restaurant_proposal_summary": summary,
                "restaurant_v2_active": True}
        if ctx.session.state.get("restaurant_v2_active"):
            from agents.front_desk_agent.restaurant_flow import credentials
            delta = {}
            if status in {"confirmed", "rejected", "expired", "conflict", "not_found"}:
                credentials.pop(ctx.session.id, None)
                ctx.session.state.pop(PENDING_RESTAURANT_PROPOSAL_KEY, None)
                ctx.session.state.pop("restaurant_proposal_summary", None)
                delta = {PENDING_RESTAURANT_PROPOSAL_KEY: "", "restaurant_proposal_summary": ""}
                if status in {"confirmed", "rejected"}:
                    ctx.session.state["restaurant_v2_active"] = False
                    delta["restaurant_v2_active"] = False
            lines = [message] if isinstance(message, str) else []
            seat_labels = {"table": "通常テーブル", "private": "個室"}
            if status == "confirmed":
                lines.append(f"{response.get('date')} {response.get('time')}、{response.get('party_size')}名、{seat_labels.get(response.get('seat_type'), '席種未確認')}、90分利用。窓際は確約できません。")
            for candidate in response.get("candidates", response.get("reservations", [])):
                if isinstance(candidate, dict):
                    lines.append(f"候補: {candidate.get('date')} {candidate.get('time')}、{candidate.get('party_size')}名、{seat_labels.get(candidate.get('seat_type'), '席種未確認')}" +
                                 (f"（予約ID: {candidate['reservation_id']}）" if 'reservation_id' in candidate else ''))
            return "\n".join(lines) or "希望条件を教えてください。", delta
        if status == "proposed":
            proposal_id = response.get("proposal_id")
            if isinstance(proposal_id, str) and proposal_id:
                ctx.session.state[PENDING_RESTAURANT_PROPOSAL_KEY] = proposal_id
                return (
                    "20時への変更案が可能です。予約はまだ変更していません。"
                    "この変更案を承認しますか？",
                    {PENDING_RESTAURANT_PROPOSAL_KEY: proposal_id},
                )
            return (
                "20時への変更案が可能です。予約はまだ変更していません。"
                "この変更案を承認しますか？",
                {},
            )
        if status in {"approved", "rejected", "not_found"}:
            ctx.session.state.pop(PENDING_RESTAURANT_PROPOSAL_KEY, None)
            state_delta = {PENDING_RESTAURANT_PROPOSAL_KEY: ""}
        else:
            state_delta = {}
        if isinstance(message, str) and message:
            return message, state_delta
        return response_text, state_delta

    def _final_event(self, ctx: InvocationContext, message: str) -> Event:
        state_delta = {key: ctx.session.state.get(key, "") for key in (
            "restaurant_v2_active", "restaurant_proposal_summary", PENDING_RESTAURANT_PROPOSAL_KEY)}
        state_delta["restaurant_structured_decision"] = None
        return Event(
            actions=EventActions(state_delta=state_delta),
            author=self.name,
            invocation_id=ctx.invocation_id,
            branch=ctx.branch,
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=message)],
            ),
        )


root_agent = FrontDeskCoordinator(
    name="front_desk_agent",
    description="ゲストの依頼を理解し、担当部署のA2A Agentへ委譲します。",
    sub_agents=[intent_agent],
)

# 3部署Agentと同様に、Front Deskも独立したA2Aサービスとして公開する。
a2a_app = to_a2a(root_agent, host="localhost", port=8004)
