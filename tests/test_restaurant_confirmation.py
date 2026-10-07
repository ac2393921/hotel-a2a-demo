"""同時確定、期限、再送、変更の原子性を検証する。"""
import asyncio
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from restaurant.domain import BookingConditions, Guest, SeatType, Reservation
from restaurant.memory import demo_repository
from restaurant.proposals import ProposalService
from restaurant.confirmation import ConfirmationService


class Clock:
    value = datetime(2026,10,7,10,tzinfo=ZoneInfo('Asia/Tokyo'))
    def now(self): return self.value


class ConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = Clock()
        self.repo = demo_repository(self.clock)
        self.proposals = ProposalService(self.repo,self.clock)
        self.confirmation = ConfirmationService(self.repo,self.clock)
        self.guest = Guest('101','デモ花子')
        self.conditions = BookingConditions(self.clock.now().replace(hour=20)+timedelta(days=1),4,SeatType.PRIVATE)

    async def proposal(self, conversation='c', original=None):
        if original: self.proposals.find(conversation,self.guest)
        return await self.proposals.propose(conversation,self.guest,self.conditions,original)

    async def confirm(self,p, conversation=None, token=None):
        return await self.confirmation.confirm(conversation or p.conversation_id,p.id,token or p.approval_token)

    async def test_concurrent_confirmations_do_not_double_book(self):
        p1,p2 = await self.proposal('c1'), await self.proposal('c2')
        results = await asyncio.gather(self.confirm(p1),self.confirm(p2))
        self.assertEqual(sorted(r['status'] for r in results),['confirmed','conflict'])
        self.assertEqual(len(self.repo.reservations()),4)

    async def test_replay_returns_same_result_without_new_booking(self):
        p = await self.proposal()
        first = await self.confirm(p)
        self.assertEqual(first,await self.confirm(p))
        self.assertEqual(len(self.repo.reservations()),4)

    async def test_wrong_conversation_token_and_expiry(self):
        p = await self.proposal()
        self.assertEqual((await self.confirm(p,'other'))['status'],'not_found')
        self.assertEqual((await self.confirm(p,token='不正token'))['status'],'not_found')
        self.clock.value += timedelta(minutes=10)
        self.assertEqual((await self.confirm(p))['status'],'expired')
        self.assertEqual(len(self.repo.reservations()),3)

    async def test_rejected_proposal_cannot_confirm(self):
        p = await self.proposal()
        await self.proposals.reject(p.conversation_id,p.id,p.approval_token)
        self.assertEqual((await self.confirm(p))['status'],'conflict')

    async def test_change_conflict_preserves_original(self):
        original = self.repo.get_reservation('demo-dinner')
        p = await self.proposal(original=original.id)
        other = await self.proposal('other')
        await self.confirm(other)
        result = await self.confirm(p)
        self.assertEqual(result['status'],'conflict')
        self.assertIn('candidates',result)
        self.assertEqual(self.repo.get_reservation(original.id),original)

    async def test_old_change_proposal_does_not_overwrite_new_version(self):
        p1 = await self.proposal(original='demo-dinner')
        p2 = await self.proposal(original='demo-dinner')
        self.assertEqual((await self.confirm(p1))['status'],'confirmed')
        changed = self.repo.get_reservation('demo-dinner')
        self.assertEqual((await self.confirm(p2))['status'],'conflict')
        self.assertEqual(self.repo.get_reservation('demo-dinner'),changed)

    async def test_storage_failure_rolls_back_reservation_and_proposal(self):
        p = await self.proposal()
        from unittest.mock import patch
        with patch.object(self.repo,'save_proposal',side_effect=RuntimeError('模擬保存失敗')):
            with self.assertRaises(RuntimeError): await self.confirm(p)
        self.assertEqual(len(self.repo.reservations()),3)
        self.assertEqual(self.repo.get_proposal(p.id),p)

    async def test_structured_confirmation_does_not_invoke_llm(self):
        from agents.restaurant_agent.consultation import ConsultationService
        from unittest.mock import AsyncMock, patch
        service = ConsultationService(self.repo,self.clock)
        p = await self.proposal()
        with patch.object(service,'_consult',new_callable=AsyncMock) as consult:
            result = await service.handle({'version':2,'action':'confirm_proposal',
                                           'conversation_id':p.conversation_id,'proposal_id':p.id,
                                           'approval_token':p.approval_token})
            self.assertEqual(result['status'],'confirmed')
            consult.assert_not_called()
            invalid = await service.handle({'version':2,'action':'confirm_proposal',
                                            'conversation_id':p.conversation_id,'proposal_id':p.id,'approved':True})
            self.assertEqual(invalid['status'],'invalid_request')
