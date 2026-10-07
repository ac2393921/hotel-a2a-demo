import json
import unittest

from agents.restaurant_agent.agent import (
    CURRENT_RESERVATION_TIME,
    PROPOSED_RESERVATION_TIME,
    RestaurantReservationStore,
    response_for_request,
)


class RestaurantReservationStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.store = RestaurantReservationStore()

    async def test_proposal_does_not_change_the_reservation(self) -> None:
        result = await self.store.handle(
            {"action": "propose_change", "requested_time": PROPOSED_RESERVATION_TIME}
        )

        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["current_time"], CURRENT_RESERVATION_TIME)
        state = await self.store.handle({"action": "get_status"})
        self.assertEqual(state["reservation_time"], CURRENT_RESERVATION_TIME)

    async def test_only_an_existing_proposal_can_be_approved(self) -> None:
        proposal = await self.store.handle(
            {"action": "propose_change", "requested_time": PROPOSED_RESERVATION_TIME}
        )

        result = await self.store.handle(
            {"action": "approve_change", "proposal_id": proposal["proposal_id"]}
        )
        state = await self.store.handle({"action": "get_status"})

        self.assertEqual(result["status"], "approved")
        self.assertEqual(state["reservation_time"], PROPOSED_RESERVATION_TIME)

    async def test_unknown_proposal_id_does_not_change_state(self) -> None:
        result = await self.store.handle(
            {"action": "approve_change", "proposal_id": "unknown"}
        )
        state = await self.store.handle({"action": "get_status"})

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(state["reservation_time"], CURRENT_RESERVATION_TIME)

    async def test_unknown_proposal_cannot_be_reported_as_rejected(self) -> None:
        result = await self.store.handle(
            {"action": "reject_change", "proposal_id": "unknown"}
        )

        self.assertEqual(result["status"], "not_found")

    async def test_rejection_discards_proposal_without_changing_state(self) -> None:
        proposal = await self.store.handle(
            {"action": "propose_change", "requested_time": PROPOSED_RESERVATION_TIME}
        )
        result = await self.store.handle(
            {"action": "reject_change", "proposal_id": proposal["proposal_id"]}
        )
        retry = await self.store.handle(
            {"action": "approve_change", "proposal_id": proposal["proposal_id"]}
        )
        state = await self.store.handle({"action": "get_status"})

        self.assertEqual(result["status"], "rejected")
        self.assertEqual(retry["status"], "not_found")
        self.assertEqual(state["reservation_time"], CURRENT_RESERVATION_TIME)

    async def test_new_store_starts_from_initial_reservation_time(self) -> None:
        result = await RestaurantReservationStore().handle({"action": "get_status"})
        self.assertEqual(result["reservation_time"], CURRENT_RESERVATION_TIME)

    async def test_invalid_command_and_oversized_input_are_rejected(self) -> None:
        invalid = await response_for_request("今すぐ20時にして", self.store)
        oversized = await response_for_request(" " * 2_001, self.store)

        self.assertEqual(json.loads(invalid)["status"], "invalid_request")
        self.assertEqual(json.loads(oversized)["status"], "invalid_request")


if __name__ == "__main__":
    unittest.main()
