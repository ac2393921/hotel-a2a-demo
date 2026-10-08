"""四つの予約シナリオをtool・公開応答・Front Desk承認境界で通す。"""
import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from agents.front_desk_agent.agent import FrontDeskCoordinator
from agents.front_desk_agent.restaurant_flow import credentials, decision_call
from agents.restaurant_agent.consultation import ConsultationService
from agents.restaurant_agent.tools import ReservationTools
from restaurant.proposals import public_proposal


class Clock:
    def now(self):
        return datetime(2026, 10, 7, 10, tzinfo=ZoneInfo('Asia/Tokyo'))


class ScenarioTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service = ConsultationService(clock=Clock())
        self.repo = self.service.repository
        credentials.clear()

    def tool(self, conversation):
        return ReservationTools(conversation, self.service.availability, self.service.proposals)

    def publish(self, tool):
        ctx = SimpleNamespace(session=SimpleNamespace(id=tool.conversation_id, state={'restaurant_v2_active': True}))
        result = public_proposal(tool.pending)
        result['approval_token'] = tool.pending.approval_token
        text, delta = FrontDeskCoordinator._handle_restaurant_response(ctx, json.dumps(result))
        self.assertNotIn(tool.pending.approval_token, text + json.dumps(delta))
        return ctx

    async def approve(self, tool, ctx):
        call = decision_call(tool.conversation_id, {'decision':'approve', 'proposal_id':tool.pending.id})
        result = await self.service.handle(json.loads(call.request_text))
        text, _ = FrontDeskCoordinator._handle_restaurant_response(ctx, json.dumps(result))
        return result, text

    def assert_no_overlap(self):
        rows = self.repo.reservations()
        for index, a in enumerate(rows):
            for b in rows[index + 1:]:
                if a.table_id == b.table_id:
                    self.assertFalse(a.conditions.start < b.conditions.start + timedelta(minutes=90)
                                     and b.conditions.start < a.conditions.start + timedelta(minutes=90))

    async def test_new_booking_is_only_saved_after_bound_approval(self):
        tool = self.tool('new')
        self.assertEqual(tool.search_availability('2026-10-08', '18:00', 2, 'table')['status'], 'available')
        await tool.propose_reservation('2026-10-08', '18:00', 2, 'table', '101', 'デモ花子', True)
        ctx = self.publish(tool)
        self.assertEqual(len(self.repo.reservations()), 3)
        result, text = await self.approve(tool, ctx)
        self.assertEqual(result['status'], 'confirmed')
        self.assertTrue(result['window_preference'])
        self.assertFalse(result['window_guaranteed'])
        self.assertIn('確定しました', text)
        self.assertEqual(len(self.repo.reservations()), 4)
        self.assert_no_overlap()

    async def test_full_private_room_offers_and_confirms_same_seat_alternative(self):
        tool = self.tool('alternative')
        search = tool.search_availability('2026-10-08', '19:00', 4, 'private')
        self.assertFalse(search['requested_available'])
        self.assertEqual(search['candidates'][0]['time'], '20:00')
        self.assertTrue(all(c['seat_type'] == 'private' for c in search['candidates']))
        await tool.propose_reservation('2026-10-08', '20:00', 4, 'private', '101', 'デモ花子', False)
        ctx = self.publish(tool)
        self.assertEqual(len(self.repo.reservations()), 3)
        self.assertEqual((await self.approve(tool, ctx))[0]['status'], 'confirmed')
        self.assert_no_overlap()

    async def test_explicit_selection_changes_only_dinner(self):
        tool = self.tool('change')
        before_dinner = self.repo.get_reservation('demo-dinner')
        before_lunch = self.repo.get_reservation('demo-lunch')
        matches = tool.find_reservations('101', 'デモ花子')
        self.assertEqual(matches['status'], 'clarification_required')
        await tool.propose_reservation_change('demo-dinner', '2026-10-08', '20:30', 4, 'table', '101', 'デモ花子', False)
        ctx = self.publish(tool)
        self.assertEqual(self.repo.get_reservation('demo-dinner'), before_dinner)
        self.assertEqual((await self.approve(tool, ctx))[0]['status'], 'confirmed')
        self.assertEqual(self.repo.get_reservation('demo-dinner').conditions.start.hour, 20)
        self.assertEqual(self.repo.get_reservation('demo-lunch'), before_lunch)
        self.assertEqual(len(self.repo.reservations()), 3)
        self.assert_no_overlap()

    async def test_approval_conflict_preserves_original_and_can_repropose(self):
        change, other = self.tool('change'), self.tool('other')
        original = self.repo.get_reservation('demo-dinner')
        change.find_reservations('101', 'デモ花子')
        await change.propose_reservation_change('demo-dinner', '2026-10-09', '20:00', 4, 'private', '101', 'デモ花子', False)
        ctx = self.publish(change)
        await other.propose_reservation('2026-10-09', '20:30', 4, 'private', '202', '架空太郎', False)
        other_ctx = self.publish(other)
        self.assertEqual((await self.approve(other, other_ctx))[0]['status'], 'confirmed')
        result, text = await self.approve(change, ctx)
        self.assertEqual(result['status'], 'conflict')
        self.assertNotIn('予約を確定しました', text)
        self.assertEqual(self.repo.get_reservation('demo-dinner'), original)
        self.assertTrue(result['candidates'])
        candidate = result['candidates'][0]
        await change.propose_reservation_change('demo-dinner', candidate['date'], candidate['time'], 4,
                                                candidate['seat_type'], '101', 'デモ花子', False)
        ctx = self.publish(change)
        self.assertEqual((await self.approve(change, ctx))[0]['status'], 'confirmed')
        self.assert_no_overlap()
