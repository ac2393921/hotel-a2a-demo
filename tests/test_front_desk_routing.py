import json
import unittest
from unittest.mock import patch

from agents.front_desk_agent.agent import build_department_calls
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


if __name__ == "__main__":
    unittest.main()
