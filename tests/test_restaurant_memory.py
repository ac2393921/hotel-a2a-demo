"""インメモリ状態の隔離と排他・巻き戻しを検証する。"""
import asyncio
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from restaurant.memory import demo_repository
from restaurant.domain import Proposal


class FixedClock:
    def now(self):
        return datetime(2026, 10, 7, 10, tzinfo=ZoneInfo('Asia/Tokyo'))


class MemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repo = demo_repository(FixedClock())

    async def test_seed_and_restart_isolation(self):
        self.assertEqual(len(self.repo.tables()), 6)
        self.assertEqual(len(self.repo.reservations()), 3)
        original = self.repo.get_reservation('demo-dinner')
        self.assertEqual(original.conditions.start.day, 8)
        async with self.repo.transaction():
            self.repo.save_reservation(replace(original, version=2))
        self.assertEqual(demo_repository(FixedClock()).get_reservation(original.id).version, 1)

    async def test_rollback_and_write_boundary(self):
        original = self.repo.get_reservation('demo-dinner')
        with self.assertRaises(RuntimeError):
            self.repo.save_reservation(replace(original, version=2))
        with self.assertRaises(ValueError):
            async with self.repo.transaction():
                self.repo.save_reservation(replace(original, version=2))
                raise ValueError('模擬失敗')
        self.assertEqual(self.repo.get_reservation(original.id), original)

    async def test_transactions_serialize_updates(self):
        async def update():
            async with self.repo.transaction():
                current = self.repo.get_reservation('demo-dinner')
                await asyncio.sleep(0)
                self.repo.save_reservation(replace(current, version=current.version + 1))
        await asyncio.gather(update(), update())
        self.assertEqual(self.repo.get_reservation('demo-dinner').version, 3)

    async def test_cancelled_transaction_rolls_back(self):
        original = self.repo.get_reservation('demo-dinner')
        with self.assertRaises(asyncio.CancelledError):
            async with self.repo.transaction():
                self.repo.save_reservation(replace(original, version=2))
                raise asyncio.CancelledError()
        self.assertEqual(self.repo.get_reservation(original.id), original)

    async def test_proposals_rollback_with_reservations(self):
        original = self.repo.get_reservation('demo-dinner')
        now = FixedClock().now()
        proposal = Proposal('p', 'conversation', '架空token', original.guest,
                            original.conditions, now, now + timedelta(minutes=10))
        with self.assertRaises(ValueError):
            async with self.repo.transaction():
                self.repo.save_reservation(replace(original, version=2))
                self.repo.save_proposal(proposal)
                raise ValueError('模擬失敗')
        self.assertIsNone(self.repo.get_proposal('p'))
        self.assertEqual(self.repo.get_reservation(original.id), original)
        async with self.repo.transaction():
            self.repo.save_proposal(proposal)
        self.assertEqual(self.repo.get_proposal('p'), proposal)
        self.assertIsNone(demo_repository(FixedClock()).get_proposal('p'))
