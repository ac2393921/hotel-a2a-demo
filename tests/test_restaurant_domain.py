"""合意した予約境界の検証。"""
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from restaurant.domain import BookingConditions, Guest, Reservation, SeatType, Table, choose_table, overlaps


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 7, 10, tzinfo=ZoneInfo('Asia/Tokyo'))

    def booking(self, hour=19, minute=0, size=2, seat=SeatType.TABLE, days=0):
        return BookingConditions(self.now.replace(hour=hour, minute=minute) + timedelta(days=days), size, seat)

    def test_operating_boundaries(self):
        for hour, minute in [(11,0),(13,30),(17,0),(20,30)]:
            self.booking(hour,minute).validate(self.now)
        for hour, minute in [(10,30),(14,0),(16,30),(21,0),(19,15)]:
            with self.assertRaises(ValueError): self.booking(hour,minute).validate(self.now)

    def test_dates_and_party_size(self):
        self.booking(days=30).validate(self.now)
        for b in [self.booking(days=31),self.booking(days=-1),self.booking(size=True),self.booking(size=7),self.booking(size=1,seat=SeatType.PRIVATE)]:
            with self.assertRaises(ValueError): b.validate(self.now)

    def test_adjacent_bookings_do_not_overlap(self):
        self.assertFalse(overlaps(self.booking(), self.booking(20,30)))
        self.assertTrue(overlaps(self.booking(), self.booking(20)))

    def test_select_smallest_available_table_without_combining(self):
        tables=[Table('four',4,SeatType.TABLE),Table('two',2,SeatType.TABLE)]
        existing=Reservation('r',Guest('101','架空ゲスト'),'two',self.booking())
        self.assertEqual(choose_table(tables,[existing],self.booking()).id,'four')
        self.assertIsNone(choose_table(tables,[],self.booking(size=6)))
        self.assertEqual(choose_table(tables,[existing],self.booking(), 'r').id,'two')
