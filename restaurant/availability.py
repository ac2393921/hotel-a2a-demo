"""公開・保存方式に依存しない空席検索ユースケース。"""
from dataclasses import dataclass, replace
from datetime import timedelta

from restaurant.domain import BookingConditions, SeatType, choose_table
from restaurant.ports import Clock, ReservationRepository


@dataclass(frozen=True)
class AvailabilityResult:
    status: str
    candidates: tuple[BookingConditions, ...] = ()
    requested_available: bool = False
    message: str = ''
    relaxation_required: bool = False


class AvailabilityService:
    def __init__(self, repository: ReservationRepository, clock: Clock):
        self.repository = repository
        self.clock = clock

    def search(self, conditions: BookingConditions, *, expand_time: bool = False,
               alternate_seat: SeatType | None = None,
               exclude_reservation_id: str | None = None) -> AvailabilityResult:
        """条件変更の許可は入力アダプターで確認し、明示的に渡す。"""
        now = self.clock.now()
        try:
            conditions.validate(now)
            if type(expand_time) is not bool:
                raise ValueError('時間範囲拡大の指定が不正です。')
            if alternate_seat is not None and not isinstance(alternate_seat, SeatType):
                raise ValueError('別席種の指定が不正です。')
        except ValueError as error:
            return AvailabilityResult('invalid_request', message=str(error))

        tables = self.repository.tables()
        reservations = self.repository.reservations()
        def available(candidate):
            return choose_table(tables, reservations, candidate, exclude_reservation_id) is not None

        if available(conditions):
            return AvailabilityResult('available', (conditions,), True,
                                      '希望条件で予約可能です。まだ確定していません。')

        local = conditions.start.astimezone(now.tzinfo)
        opening, last_start = (660, 810) if local.hour < 15 else (1020, 1230)
        candidates = []
        for minute in range(opening, last_start + 1, 30):
            start = local.replace(hour=minute // 60, minute=minute % 60)
            if not expand_time and abs(start - local) > timedelta(minutes=60):
                continue
            candidate = replace(conditions, start=start)
            try:
                candidate.validate(now)
            except ValueError:
                continue
            if available(candidate):
                candidates.append(candidate)
        candidates.sort(key=lambda c: (abs(c.start - local), c.start))
        if candidates:
            return AvailabilityResult('available', tuple(candidates[:3]), False,
                                      '希望時刻は満席です。同じ席種の代替時刻があります。')

        if alternate_seat is not None:
            alternate = replace(conditions, seat_type=alternate_seat)
            return self.search(alternate, expand_time=expand_time,
                               exclude_reservation_id=exclude_reservation_id)
        return AvailabilityResult('unavailable', message='条件内に空席がありません。別の席種や時間範囲も調べますか。',
                                  relaxation_required=True)
