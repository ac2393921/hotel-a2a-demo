import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from google.adk.events import Event
from google.genai import types

from agents.front_desk_agent import agent as front_desk
from agents.front_desk_agent.agent import A2A_METADATA_PREFIX, build_department_calls
from agents.front_desk_agent.intent import IntentExtractionResult


class FrontDeskRoutingTests(unittest.TestCase):
    def test_dispatch_only_creates_calls_for_selected_departments(self) -> None:
        intent = IntentExtractionResult.model_validate(
            {
                "decision": "dispatch",
                "requests": [
                    {
                        "department": "maintenance_agent",
                        "operation": "check_repair",
                        "details": "エアコンの修理可否を確認してください",
                    }
                ],
                "response_message": None,
            }
        )

        with patch.dict("os.environ", {}, clear=True):
            calls = build_department_calls(intent)

        self.assertEqual([call.name for call in calls], ["maintenance_agent"])
        self.assertEqual(
            calls[0].agent_card,
            "http://localhost:8001/.well-known/agent-card.json",
        )
        self.assertEqual(calls[0].request_text, "エアコンの修理可否を確認してください")

    def test_restaurant_call_uses_the_fixed_mvp_change_proposal(self) -> None:
        intent = IntentExtractionResult.model_validate(
            {
                "decision": "dispatch",
                "requests": [
                    {
                        "department": "restaurant_agent",
                        "operation": "propose_reservation_time_change",
                        "details": "19時の予約時刻を確認してください",
                        "reservation_time": "19:00",
                        "requested_time": None,
                    }
                ],
                "response_message": None,
            }
        )

        calls = build_department_calls(intent)

        self.assertEqual([call.name for call in calls], ["restaurant_agent"])
        self.assertEqual(
            json.loads(calls[0].request_text),
            {"action": "propose_change", "requested_time": "20:00"},
        )

    def test_non_dispatch_decisions_do_not_create_a2a_calls(self) -> None:
        intent = IntentExtractionResult.model_validate(
            {
                "decision": "clarify",
                "requests": [],
                "response_message": "予約時刻を教えてください。",
            }
        )

        self.assertEqual(build_department_calls(intent), [])

    def test_routes_the_representative_scenario_to_all_three_departments(self) -> None:
        intent = IntentExtractionResult.model_validate(
            {
                "decision": "dispatch",
                "requests": [
                    {
                        "department": "maintenance_agent",
                        "operation": "check_repair",
                        "details": "エアコンの修理可否",
                    },
                    {
                        "department": "housekeeping_agent",
                        "operation": "check_alternative_room",
                        "details": "代替部屋の有無",
                    },
                    {
                        "department": "restaurant_agent",
                        "operation": "propose_reservation_time_change",
                        "details": "19時予約の変更案",
                        "reservation_time": "19:00",
                    },
                ],
                "response_message": None,
            }
        )

        calls = build_department_calls(intent)

        self.assertEqual(
            [call.name for call in calls],
            ["maintenance_agent", "housekeeping_agent", "restaurant_agent"],
        )


class FrontDeskCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_runs_selected_agents_in_parallel_and_aggregates_responses(self) -> None:
        intent_json = json.dumps(
            {
                "decision": "dispatch",
                "requests": [
                    {
                        "department": "maintenance_agent",
                        "operation": "check_repair",
                        "details": "エアコンを確認",
                        "reservation_time": "",
                        "requested_time": "",
                    },
                    {
                        "department": "restaurant_agent",
                        "operation": "propose_reservation_time_change",
                        "details": "予約変更案を確認",
                        "reservation_time": "19:00",
                        "requested_time": "",
                    },
                ],
                "response_message": "",
            }
        )
        active = 0
        peak_active = 0
        both_started = asyncio.Event()

        class FakeRemoteAgent:
            def __init__(self, name: str, answer: str) -> None:
                self.name = name
                self.answer = answer

            async def cleanup(self) -> None:
                return None

            async def run_async(self, _ctx):
                nonlocal active, peak_active
                active += 1
                peak_active = max(peak_active, active)
                if active == 2:
                    both_started.set()
                await asyncio.wait_for(both_started.wait(), timeout=1)
                yield Event(
                    author=self.name,
                    invocation_id="invocation-1",
                    content=types.Content(
                        role="model", parts=[types.Part.from_text(text=self.answer)]
                    ),
                    custom_metadata={
                        f"{A2A_METADATA_PREFIX}response": {
                            "status": {"state": "TASK_STATE_COMPLETED"}
                        },
                        f"{A2A_METADATA_PREFIX}task_id": f"task-{self.name}",
                    },
                )
                active -= 1

        async def intent_events(_ctx):
            yield Event(
                author="front_desk_intent_agent",
                invocation_id="invocation-1",
                content=types.Content(
                    role="model", parts=[types.Part.from_text(text=intent_json)]
                ),
                finish_reason=types.FinishReason.STOP,
            )

        def make_remote(call):
            answer = {
                "maintenance_agent": "修理担当を手配できます。",
                "restaurant_agent": "20時への変更案を提示できます。",
            }[call.name]
            return FakeRemoteAgent(call.name, answer)

        ctx = SimpleNamespace(invocation_id="invocation-1", branch="main", state={})
        with (
            patch.object(
                front_desk,
                "intent_agent",
                SimpleNamespace(name="front_desk_intent_agent", run_async=intent_events),
            ),
            patch.object(front_desk, "_create_remote_agent", side_effect=make_remote),
        ):
            # ParallelAgentと同じインターフェースで子Agentを並列起動する。
            class ParallelRunner:
                def __init__(self, *, sub_agents, **_kwargs):
                    self.sub_agents = sub_agents

                async def run_async(self, context):
                    async def collect(agent):
                        return [event async for event in agent.run_async(context)]

                    for child_events in await asyncio.gather(
                        *(collect(agent) for agent in self.sub_agents)
                    ):
                        for event in child_events:
                            yield event

            with patch.object(front_desk, "ParallelAgent", ParallelRunner):
                events = [
                    event
                    async for event in front_desk.root_agent._run_async_impl(ctx)
                ]

        self.assertEqual(peak_active, 2)
        final_text = events[-1].content.parts[0].text
        self.assertIn("maintenance_agent", final_text)
        self.assertIn("restaurant_agent", final_text)
        self.assertNotIn("housekeeping_agent", final_text)
        self.assertIn("task-maintenance_agent", final_text)
        self.assertIn("task-restaurant_agent", final_text)
        self.assertIn("修理担当を手配できます。", final_text)
        self.assertIn("20時への変更案を提示できます。", final_text)

    async def test_clarification_does_not_call_department_agents(self) -> None:
        intent_json = json.dumps(
            {
                "decision": "clarify",
                "requests": [],
                "response_message": "現在のレストラン予約時刻を教えてください。",
            },
            ensure_ascii=False,
        )

        async def intent_events(_ctx):
            yield Event(
                author="front_desk_intent_agent",
                invocation_id="invocation-1",
                content=types.Content(
                    role="model", parts=[types.Part.from_text(text=intent_json)]
                ),
                finish_reason=types.FinishReason.STOP,
            )

        ctx = SimpleNamespace(invocation_id="invocation-1", branch="main", state={})
        with (
            patch.object(
                front_desk,
                "intent_agent",
                SimpleNamespace(name="front_desk_intent_agent", run_async=intent_events),
            ),
            patch.object(front_desk, "_create_remote_agent") as create_remote,
        ):
            events = [
                event
                async for event in front_desk.root_agent._run_async_impl(ctx)
            ]

        create_remote.assert_not_called()
        self.assertIn("現在のレストラン予約時刻", events[-1].content.parts[0].text)


if __name__ == "__main__":
    unittest.main()
