"""予約照合・選択・提案の非確定境界を検証する。"""
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from restaurant.domain import BookingConditions, Guest, Proposal, SeatType
from restaurant.memory import demo_repository
from restaurant.proposals import ProposalService, public_proposal


class FixedClock:
    def now(self):
        return datetime(2026, 10, 7, 10, tzinfo=ZoneInfo('Asia/Tokyo'))


class ProposalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FixedClock()
        self.repo = demo_repository(self.clock)
        self.service = ProposalService(self.repo, self.clock)
        self.guest = Guest('101', 'デモ花子')
        self.conditions = BookingConditions(self.clock.now().replace(hour=20) + timedelta(days=1), 4, SeatType.TABLE, True)

    async def test_failed_lookup_exposes_no_candidates(self):
        result = self.service.find('c', Guest('101', '別の架空ゲスト'))
        self.assertEqual(result['status'], 'not_found')
        self.assertEqual(result['reservations'], [])

    async def test_multiple_reservations_require_explicit_selection(self):
        result = self.service.find('c', self.guest)
        self.assertEqual(result['status'], 'clarification_required')
        self.assertEqual(len(result['reservations']), 2)
        denied = await self.service.propose('other', self.guest, self.conditions, 'demo-dinner')
        self.assertEqual(denied['status'], 'not_found')

    async def test_change_proposal_keeps_original_and_summary(self):
        original = self.repo.get_reservation('demo-dinner')
        self.service.find('c', self.guest)
        proposal = await self.service.propose('c', self.guest, self.conditions, original.id)
        self.assertIsInstance(proposal, Proposal)
        self.assertEqual(proposal.reservation_version, original.version)
        self.assertEqual(self.repo.get_reservation(original.id), original)
        public = public_proposal(proposal)
        for text in ['2026-10-08 20:00', '4名', '通常テーブル', '90分', '確約できません']:
            self.assertIn(text, public['summary'])
        self.assertNotIn('approval_token', public)
        self.assertEqual(proposal.expires_at - proposal.created_at, timedelta(minutes=10))

    async def test_new_proposals_do_not_hold_tables(self):
        first = await self.service.propose('c1', self.guest, self.conditions)
        second = await self.service.propose('c2', self.guest, self.conditions)
        self.assertIsInstance(first, Proposal)
        self.assertIsInstance(second, Proposal)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(self.repo.reservations()), 3)

    async def test_reject_is_conversation_bound_and_does_not_change_booking(self):
        proposal = await self.service.propose('c', self.guest, self.conditions)
        denied = await self.service.reject('other', proposal.id, proposal.approval_token)
        self.assertEqual(denied['status'], 'not_found')
        result = await self.service.reject('c', proposal.id, proposal.approval_token)
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(len(self.repo.reservations()), 3)

    async def test_representations_hide_token_and_guest_identifiers(self):
        proposal = await self.service.propose('c', self.guest, self.conditions)
        self.assertNotIn(proposal.approval_token, repr(proposal))
        self.assertNotIn(self.guest.name, repr(proposal))
        self.assertNotIn('room_number=', repr(proposal))
