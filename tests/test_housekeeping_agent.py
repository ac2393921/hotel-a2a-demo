import unittest

from agents.housekeeping_agent.agent import (
    EMPTY_REQUEST_RESPONSE,
    LONG_REQUEST_RESPONSE,
    ROOM_AVAILABLE_RESPONSE,
    UNSUPPORTED_REQUEST_RESPONSE,
    response_for_request,
)


class HousekeepingAgentResponseTests(unittest.TestCase):
    def test_alternative_room_request_gets_the_fixed_availability(self) -> None:
        self.assertEqual(
            response_for_request("エアコン故障のため代替部屋を確認してください"),
            ROOM_AVAILABLE_RESPONSE,
        )

    def test_empty_request_asks_what_room_support_is_needed(self) -> None:
        self.assertEqual(response_for_request("  \n "), EMPTY_REQUEST_RESPONSE)

    def test_restaurant_request_is_out_of_scope(self) -> None:
        self.assertEqual(
            response_for_request("19時のレストラン予約を変更してください"),
            UNSUPPORTED_REQUEST_RESPONSE,
        )

    def test_oversized_request_is_rejected_without_echoing_input(self) -> None:
        request = "代替部屋" + "個人情報" * 500
        self.assertEqual(response_for_request(request), LONG_REQUEST_RESPONSE)
        self.assertNotIn("個人情報", LONG_REQUEST_RESPONSE)


if __name__ == "__main__":
    unittest.main()
