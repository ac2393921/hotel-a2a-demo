import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from google.adk.events import Event
from google.genai import types

from agents.front_desk_agent import agent as front_desk
from agents.front_desk_agent.agent import A2A_METADATA_PREFIX


class ScriptedIntentAgent:
    name = "front_desk_intent_agent"

    async def run_async(self, _ctx):
        output = json.dumps(
            {
                "decision": "dispatch",
                "requests": [
                    {
                        "department": "maintenance_agent",
                        "operation": "check_repair",
                        "details": "エアコンの修理可否を確認",
                        "reservation_time": "",
                        "requested_time": "",
                    },
                    {
                        "department": "housekeeping_agent",
                        "operation": "check_alternative_room",
                        "details": "代替部屋の有無を確認",
                        "reservation_time": "",
                        "requested_time": "",
                    },
                ],
                "response_message": "",
            },
            ensure_ascii=False,
        )
        yield Event(
            author=self.name,
            invocation_id="invocation-1",
            content=types.Content(
                role="model", parts=[types.Part.from_text(text=output)]
            ),
            finish_reason=types.FinishReason.STOP,
        )


class FakeRemoteAgent:
    def __init__(self, name: str, *, fail: bool = False) -> None:
        self.name = name
        self.fail = fail

    async def cleanup(self) -> None:
        return None

    async def run_async(self, _ctx):
        if self.fail:
            raise RuntimeError("connection failed: token=secret-value")
        yield Event(
            author=self.name,
            invocation_id="invocation-1",
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text="代替部屋を1室確保できます。")],
            ),
            custom_metadata={
                f"{A2A_METADATA_PREFIX}task_id": "housekeeping-task",
                f"{A2A_METADATA_PREFIX}response": {
                    "status": {"state": "TASK_STATE_COMPLETED"}
                },
            },
        )


class FakeParallelAgent:
    def __init__(self, *, sub_agents, **_kwargs) -> None:
        self.sub_agents = sub_agents

    async def run_async(self, ctx):
        async def collect(agent):
            return [event async for event in agent._run_async_impl(ctx)]

        results = await asyncio.gather(
            *(collect(agent) for agent in self.sub_agents)
        )
        for events in results:
            for event in events:
                yield event


class FrontDeskPartialFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_remote_exception_keeps_other_department_result_and_hides_details(
        self,
    ) -> None:
        ctx = SimpleNamespace(
            invocation_id="invocation-1", branch="main", state={}
        )

        def create_remote(call):
            return FakeRemoteAgent(
                call.name, fail=(call.name == "maintenance_agent")
            )

        with (
            patch.object(front_desk, "intent_agent", ScriptedIntentAgent()),
            patch.object(front_desk, "_create_remote_agent", side_effect=create_remote),
            patch.object(front_desk, "ParallelAgent", FakeParallelAgent),
        ):
            events = [
                event
                async for event in front_desk.root_agent._run_async_impl(ctx)
            ]

        output = events[-1].content.parts[0].text
        self.assertIn("Maintenance Agent [失敗]", output)
        self.assertIn("Housekeeping Agent [完了]", output)
        self.assertIn("代替部屋を1室確保できます。", output)
        self.assertNotIn("token=secret-value", output)
        self.assertNotIn("connection failed", output)
        self.assertTrue(
            all(
                "secret-value" not in event.model_dump_json()
                for event in events
            )
        )
        failure_events = [event for event in events if event.error_message]
        self.assertEqual(len(failure_events), 1)
        self.assertEqual(
            failure_events[0].error_message,
            "部署AgentとのA2A通信に失敗しました。",
        )


if __name__ == "__main__":
    unittest.main()
