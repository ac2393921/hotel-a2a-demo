import unittest

from agents.maintenance_agent.agent import (
    EMPTY_REQUEST_RESPONSE,
    LONG_REQUEST_RESPONSE,
    REPAIR_RESPONSE,
    UNSUPPORTED_REQUEST_RESPONSE,
    response_for_request,
)


class MaintenanceAgentResponseTests(unittest.TestCase):
    def test_equipment_failure_gets_the_fixed_repair_estimate(self) -> None:
        self.assertEqual(
            response_for_request("部屋のエアコンが壊れていて困っています"),
            REPAIR_RESPONSE,
        )

    def test_empty_request_asks_for_equipment_and_symptom(self) -> None:
        self.assertEqual(response_for_request("  \n "), EMPTY_REQUEST_RESPONSE)

    def test_out_of_scope_request_does_not_claim_maintenance_can_handle_it(self) -> None:
        self.assertEqual(
            response_for_request("19時のレストラン予約を変更してください"),
            UNSUPPORTED_REQUEST_RESPONSE,
        )

    def test_oversized_request_is_rejected_without_echoing_input(self) -> None:
        request = "エアコン故障" + "個人情報" * 500
        self.assertEqual(response_for_request(request), LONG_REQUEST_RESPONSE)
        self.assertNotIn("個人情報", LONG_REQUEST_RESPONSE)


if __name__ == "__main__":
    unittest.main()
