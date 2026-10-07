"""単一プロセスの架空予約Repositoryとホテル時刻。"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from restaurant.domain import BookingConditions, Guest, Proposal, Reservation, SeatType, Table
from restaurant.ports import Clock


class HotelClock:
    def __init__(self, timezone: str = 'Asia/Tokyo') -> None:
        self.timezone = ZoneInfo(timezone)

    def now(self) -> datetime:
        return datetime.now(self.timezone)


class InMemoryRepository:
    """不変モデルを保存し、例外時は予約と提案を同時に巻き戻す。"""

    def __init__(self, tables: list[Table], reservations: list[Reservation] | None = None):
        if len({t.id for t in tables}) != len(tables):
            raise ValueError('卓IDが重複しています。')
        self._tables = tuple(tables)
        self._reservations = {r.id: r for r in (reservations or [])}
        self._proposals: dict[str, Proposal] = {}
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task | None = None

    @asynccontextmanager
    async def transaction(self):
        if self._owner is asyncio.current_task():
            raise RuntimeError('transactionの入れ子はできません。')
        async with self._lock:
            self._owner = asyncio.current_task()
            reservations = self._reservations.copy()
            proposals = self._proposals.copy()
            try:
                yield
            except BaseException:
                self._reservations = reservations
                self._proposals = proposals
                raise
            finally:
                self._owner = None

    def _require_transaction(self) -> None:
        if self._owner is not asyncio.current_task():
            raise RuntimeError('更新にはtransactionが必要です。')

    def tables(self) -> list[Table]:
        return list(self._tables)

    def reservations(self) -> list[Reservation]:
        return list(self._reservations.values())

    def get_reservation(self, reservation_id: str) -> Reservation | None:
        return self._reservations.get(reservation_id)

    def save_reservation(self, reservation: Reservation) -> None:
        self._require_transaction()
        self._reservations[reservation.id] = reservation

    def get_proposal(self, proposal_id: str) -> Proposal | None:
        return self._proposals.get(proposal_id)

    def save_proposal(self, proposal: Proposal) -> None:
        self._require_transaction()
        self._proposals[proposal.id] = proposal


def demo_repository(clock: Clock) -> InMemoryRepository:
    """翌日の架空データで、日付によらず同じ相談場面を再現する。"""
    day = clock.now() + timedelta(days=1)
    tables = [Table('T2-1', 2, SeatType.TABLE), Table('T2-2', 2, SeatType.TABLE),
              Table('T4-1', 4, SeatType.TABLE), Table('T4-2', 4, SeatType.TABLE),
              Table('T6-1', 6, SeatType.TABLE), Table('P6-1', 6, SeatType.PRIVATE)]
    guest = Guest('101', 'デモ花子')
    def at(hour, minute, size, seat):
        return BookingConditions(day.replace(hour=hour, minute=minute, second=0, microsecond=0), size, seat)
    reservations = [
        Reservation('demo-dinner', guest, 'T4-1', at(19, 0, 4, SeatType.TABLE)),
        Reservation('demo-lunch', guest, 'T2-1', at(12, 0, 2, SeatType.TABLE)),
        Reservation('demo-private', Guest('202', '架空太郎'), 'P6-1', at(18, 30, 4, SeatType.PRIVATE)),
    ]
    return InMemoryRepository(tables, reservations)
