import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from google.adk.events import Event
from google.genai import types

from agents.front_desk_agent import agent as front_desk
from agents.front_desk_agent.agent import (
    A2A_METADATA_PREFIX,
    PENDING_RESTAURANT_PROPOSAL_KEY,
    build_approval_call,
)
from agents.restaurant_agent.agent import (
    CURRENT_RESERVATION_TIME,
    PROPOSED_RESERVATION_TIME,
    RestaurantReservationStore,
    response_for_request,
)


def _model_output(decision: str) -> str:
    requests = []
    if decision == "dispatch":
        requests = [
            {
                "department": "restaurant_agent",
                "operation": "propose_reservation_time_change",
                "details": "19時の予約を20時に変更できるか確認",
                "reservation_time": "19:00",
                "requested_time": "",
            }
        ]
    return json.dumps(
        {
            "decision": decision,
            "requests": requests,
            "response_message": (
                "変更案への回答をもう少し詳しく教えてください。"
                if decision == "clarify"
                else ""
            ),
        }
    )


class ScriptedIntentAgent:
    name = "front_desk_intent_agent"

    def __init__(self, decisions: list[str]) -> None:
        self._outputs = [_model_output(decision) for decision in decisions]

    async def run_async(self, _ctx):
        output = self._outputs.pop(0)
        yield Event(
            author=self.name,
            invocation_id="invocation-1",
            content=types.Content(
                role="model", parts=[types.Part.from_text(text=output)]
            ),
            finish_reason=types.FinishReason.STOP,
        )


class FakeRestaurantAgent:
    def __init__(self, call, store: RestaurantReservationStore) -> None:
        self.name = call.name
        self.call = call
        self.store = store

    async def cleanup(self) -> None:
        return None

    async def run_async(self, _ctx):
        response = await response_for_request(self.call.request_text, self.store)
        yield Event(
            author=self.name,
            invocation_id="invocation-1",
            content=types.Content(
                role="model", parts=[types.Part.from_text(text=response)]
            ),
            custom_metadata={
                f"{A2A_METADATA_PREFIX}task_id": "restaurant-task",
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


class FrontDeskApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def _run_conversation(self, decisions: list[str]):
        state: dict[str, str] = {}
        store = RestaurantReservationStore()
        intent = ScriptedIntentAgent(decisions)

        def make_remote(call):
            return FakeRestaurantAgent(call, store)

        async def invoke():
            ctx = SimpleNamespace(
                invocation_id="invocation-1",
                branch="main",
                session=SimpleNamespace(state=state),
            )
            with (
                patch.object(front_desk, "intent_agent", intent),
                patch.object(front_desk, "ParallelAgent", FakeParallelAgent),
                patch.object(front_desk, "_create_remote_agent", side_effect=make_remote),
            ):
                return [
                    event
                    async for event in front_desk.root_agent._run_async_impl(ctx)
                ]

        return state, store, invoke

    async def test_guest_approval_in_the_same_session_updates_only_the_proposed_time(
        self,
    ) -> None:
        state, store, invoke = await self._run_conversation(["dispatch", "approve"])

        proposal_events = await invoke()
        proposal_id = state[PENDING_RESTAURANT_PROPOSAL_KEY]
        before_approval = await store.handle({"action": "get_status"})
        self.assertEqual(before_approval["reservation_time"], CURRENT_RESERVATION_TIME)
        self.assertIn("承認しますか", proposal_events[-1].content.parts[0].text)
        self.assertTrue(
            all(
                proposal_id not in (part.text or "")
                for event in proposal_events
                if event.content
                for part in event.content.parts
            )
        )
        self.assertTrue(
            any(
                (event.actions.state_delta or {}).get(PENDING_RESTAURANT_PROPOSAL_KEY)
                == proposal_id
                for event in proposal_events
            )
        )

        approval_events = await invoke()
        after_approval = await store.handle({"action": "get_status"})

        self.assertEqual(after_approval["reservation_time"], PROPOSED_RESERVATION_TIME)
        self.assertNotIn(PENDING_RESTAURANT_PROPOSAL_KEY, state)
        self.assertIn("予約を20時に変更しました", approval_events[-1].content.parts[0].text)

    async def test_guest_rejection_discards_proposal_without_changing_reservation(
        self,
    ) -> None:
        state, store, invoke = await self._run_conversation(["dispatch", "reject"])

        await invoke()
        proposal_id = state[PENDING_RESTAURANT_PROPOSAL_KEY]
        reject_call = build_approval_call("reject", proposal_id)
        self.assertEqual(
            json.loads(reject_call.request_text),
            {"action": "reject_change", "proposal_id": proposal_id},
        )

        events = await invoke()
        after_rejection = await store.handle({"action": "get_status"})

        self.assertEqual(after_rejection["reservation_time"], CURRENT_RESERVATION_TIME)
        self.assertNotIn(PENDING_RESTAURANT_PROPOSAL_KEY, state)
        self.assertIn("変更案を取り下げました", events[-1].content.parts[0].text)

    async def test_ambiguous_response_keeps_reservation_unchanged_and_proposal_pending(
        self,
    ) -> None:
        state, store, invoke = await self._run_conversation(["dispatch", "clarify"])

        await invoke()
        proposal_id = state[PENDING_RESTAURANT_PROPOSAL_KEY]
        events = await invoke()
        after_clarification = await store.handle({"action": "get_status"})

        self.assertEqual(after_clarification["reservation_time"], CURRENT_RESERVATION_TIME)
        self.assertEqual(state[PENDING_RESTAURANT_PROPOSAL_KEY], proposal_id)
        self.assertIn("もう少し詳しく", events[-1].content.parts[0].text)

    async def test_approval_without_a_pending_proposal_does_not_call_restaurant(self) -> None:
        state: dict[str, str] = {}
        intent = ScriptedIntentAgent(["approve"])
        ctx = SimpleNamespace(
            invocation_id="invocation-1",
            branch="main",
            session=SimpleNamespace(state=state),
        )
        with (
            patch.object(front_desk, "intent_agent", intent),
            patch.object(front_desk, "_create_remote_agent") as create_remote,
        ):
            events = [
                event
                async for event in front_desk.root_agent._run_async_impl(ctx)
            ]

        create_remote.assert_not_called()
        self.assertIn("有効な変更案が見つかりません", events[-1].content.parts[0].text)


if __name__ == "__main__":
    unittest.main()
