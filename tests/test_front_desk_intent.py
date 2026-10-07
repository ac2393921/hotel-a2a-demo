import unittest

from pydantic import ValidationError

from agents.front_desk_agent.intent import (
    IntentExtractionResult,
    validate_intent_output,
)


class IntentExtractionValidationTests(unittest.TestCase):
    def test_accepts_three_department_requests_for_the_representative_scenario(self) -> None:
        result = IntentExtractionResult.model_validate(
            {
                "decision": "dispatch",
                "requests": [
                    {
                        "department": "maintenance_agent",
                        "operation": "check_repair",
                        "details": "エアコンの故障を確認してください",
                        "reservation_time": None,
                        "requested_time": None,
                    },
                    {
                        "department": "housekeeping_agent",
                        "operation": "check_alternative_room",
                        "details": "エアコン故障のため代替部屋を確認してください",
                        "reservation_time": None,
                        "requested_time": None,
                    },
                    {
                        "department": "restaurant_agent",
                        "operation": "propose_reservation_time_change",
                        "details": "19時の予約を20時へ変更できるか照会してください",
                        "reservation_time": "19:00",
                        "requested_time": "20:00",
                    },
                ],
                "response_message": None,
            }
        )

        self.assertEqual(result.decision, "dispatch")
        self.assertEqual(len(result.requests), 3)
        self.assertEqual(result.requests[-1].requested_time, "20:00")

    def test_clarification_cannot_include_dispatch_requests(self) -> None:
        with self.assertRaises(ValidationError):
            IntentExtractionResult.model_validate(
                {
                    "decision": "clarify",
                    "requests": [
                        {
                            "department": "maintenance_agent",
                            "operation": "check_repair",
                            "details": "エアコンを修理してください",
                        }
                    ],
                    "response_message": "客室番号を教えてください。",
                }
            )

    def test_department_and_operation_mismatch_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            IntentExtractionResult.model_validate(
                {
                    "decision": "dispatch",
                    "requests": [
                        {
                            "department": "restaurant_agent",
                            "operation": "check_repair",
                            "details": "エアコンを確認してください",
                            "reservation_time": None,
                            "requested_time": None,
                        }
                    ],
                    "response_message": None,
                }
            )

    def test_restaurant_intent_needs_current_reservation_time_only(self) -> None:
        result = IntentExtractionResult.model_validate(
            {
                "decision": "dispatch",
                "requests": [
                    {
                        "department": "restaurant_agent",
                        "operation": "propose_reservation_time_change",
                        "details": "19時の予約の変更案を確認してください",
                        "reservation_time": "19:00",
                        "requested_time": None,
                    }
                ],
                "response_message": None,
            }
        )
        self.assertEqual(result.requests[0].reservation_time, "19:00")
        self.assertIsNone(result.requests[0].requested_time)

    def test_restaurant_change_requires_current_reservation_time(self) -> None:
        with self.assertRaises(ValidationError):
            IntentExtractionResult.model_validate(
                {
                    "decision": "dispatch",
                    "requests": [
                        {
                            "department": "restaurant_agent",
                            "operation": "propose_reservation_time_change",
                            "details": "予約を変更できるか確認してください",
                            "reservation_time": None,
                            "requested_time": None,
                        }
                    ],
                    "response_message": None,
                }
            )

    def test_unsupported_response_cannot_include_requests(self) -> None:
        result = IntentExtractionResult.model_validate(
            {
                "decision": "unsupported",
                "requests": [],
                "response_message": "そのご依頼には対応できません。",
            }
        )
        self.assertEqual(result.requests, [])

    def test_validate_model_output_rejects_malformed_json(self) -> None:
        with self.assertRaises(ValidationError):
            validate_intent_output('{"decision":"dispatch","requests":[]}')

    def test_missing_current_reservation_time_becomes_clarification(self) -> None:
        result = validate_intent_output(
            '{"decision":"dispatch","requests":[{"department":"restaurant_agent",'
            '"operation":"propose_reservation_time_change","details":"予約を20時へ変更",'
            '"reservation_time":"","requested_time":"20:00"}],"response_message":""}'
        )
        self.assertEqual(result.decision, "clarify")
        self.assertEqual(result.requests, [])
        self.assertIn("現在", result.response_message or "")


if __name__ == "__main__":
    unittest.main()
