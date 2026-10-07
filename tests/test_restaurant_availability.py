"""空席検索の同日・営業枠・希望条件を検証する。"""
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from restaurant.availability import AvailabilityService
from restaurant.domain import BookingConditions, SeatType
from restaurant.memory import demo_repository, InMemoryRepository


class FixedClock:
    def now(self):
        return datetime(2026, 10, 7, 10, tzinfo=ZoneInfo('Asia/Tokyo'))


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.clock = FixedClock()
        self.repo = demo_repository(self.clock)
        self.service = AvailabilityService(self.repo, self.clock)

    def conditions(self, hour=19, minute=0, seat=SeatType.PRIVATE, size=4):
        return BookingConditions(self.clock.now().replace(hour=hour, minute=minute) + timedelta(days=1), size, seat)

    def test_available_does_not_reserve(self):
        result = self.service.search(self.conditions(seat=SeatType.TABLE))
        self.assertTrue(result.requested_available)
        self.assertEqual(len(self.repo.reservations()), 3)

    def test_private_alternatives_preserve_conditions(self):
        result = self.service.search(self.conditions())
        self.assertEqual(result.status, 'available')
        self.assertFalse(result.requested_available)
        self.assertEqual([c.start.strftime('%H:%M') for c in result.candidates], ['20:00'])
        self.assertTrue(all(c.seat_type == SeatType.PRIVATE and c.party_size == 4 for c in result.candidates))

    def test_no_candidates_is_business_result(self):
        repo = InMemoryRepository([], [])
        result = AvailabilityService(repo, self.clock).search(self.conditions())
        self.assertEqual(result.status, 'unavailable')
        self.assertTrue(result.relaxation_required)

    def test_invalid_operating_time(self):
        for hour, minute in [(14,0),(16,0),(21,0)]:
            self.assertEqual(self.service.search(self.conditions(hour, minute)).status, 'invalid_request')

    def test_at_most_three_unique_nearest_candidates(self):
        result = self.service.search(self.conditions(19,30), expand_time=True)
        starts = [c.start.strftime('%H:%M') for c in result.candidates]
        self.assertEqual(starts, ['20:00','20:30','17:00'])
        self.assertEqual(len(starts), len(set(starts)))
        self.assertTrue(all(c.start.date() == self.conditions().start.date() for c in result.candidates))

    def test_does_not_change_seat_without_explicit_input(self):
        repo = InMemoryRepository([t for t in self.repo.tables() if t.seat_type == SeatType.TABLE])
        service = AvailabilityService(repo, self.clock)
        self.assertEqual(service.search(self.conditions()).status, 'unavailable')
        result = service.search(self.conditions(), alternate_seat=SeatType.TABLE)
        self.assertTrue(result.requested_available)
        self.assertEqual(result.candidates[0].seat_type, SeatType.TABLE)

    def test_default_search_never_expands_beyond_sixty_minutes(self):
        result = self.service.search(self.conditions(19,30))
        self.assertEqual([c.start.strftime('%H:%M') for c in result.candidates], ['20:00', '20:30'])
        self.assertTrue(all(abs(c.start - self.conditions(19,30).start) <= timedelta(minutes=60) for c in result.candidates))
