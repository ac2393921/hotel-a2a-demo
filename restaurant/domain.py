"""通信と保存に依存しない予約ルール。"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum


class SeatType(StrEnum):
    TABLE = 'table'
    PRIVATE = 'private'


@dataclass(frozen=True)
class Table:
    id: str
    capacity: int
    seat_type: SeatType

    def __post_init__(self):
        if not self.id or type(self.capacity) is not int or self.capacity < 1:
            raise ValueError('卓の設定が不正です。')
        if not isinstance(self.seat_type, SeatType):
            raise ValueError('席種が不正です。')


@dataclass(frozen=True)
class BookingConditions:
    start: datetime
    party_size: int
    seat_type: SeatType
    window_preference: bool = False

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=90)

    def validate(self, now: datetime) -> None:
        if self.start.tzinfo is None or now.tzinfo is None:
            raise ValueError('タイムゾーンが必要です。')
        if type(self.party_size) is not int or not 1 <= self.party_size <= 6:
            raise ValueError('人数は1〜6名です。')
        if not isinstance(self.seat_type, SeatType):
            raise ValueError('席種が不正です。')
        if type(self.window_preference) is not bool:
            raise ValueError('窓際希望は真偽値です。')
        if self.seat_type == SeatType.PRIVATE and self.party_size < 2:
            raise ValueError('個室は2〜6名です。')
        local = self.start.astimezone(now.tzinfo)
        if local < now or not 0 <= (local.date() - now.date()).days <= 30:
            raise ValueError('予約可能期間外です。')
        if local.minute not in (0, 30) or local.second or local.microsecond:
            raise ValueError('開始時刻は30分刻みです。')
        minutes = local.hour * 60 + local.minute
        if not (660 <= minutes <= 810 or 1020 <= minutes <= 1230):
            raise ValueError('営業時間内に90分を確保できません。')


@dataclass(frozen=True)
class Guest:
    room_number: str = field(repr=False)
    name: str = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.room_number, str) or not 1 <= len(self.room_number.strip()) <= 20:
            raise ValueError('部屋番号が不正です。')
        if not isinstance(self.name, str) or not 1 <= len(self.name.strip()) <= 100:
            raise ValueError('氏名が不正です。')


@dataclass(frozen=True)
class Reservation:
    id: str
    guest: Guest
    table_id: str
    conditions: BookingConditions
    version: int = 1


class ProposalStatus(StrEnum):
    PENDING = 'pending'
    CONFIRMED = 'confirmed'
    REJECTED = 'rejected'
    CONFLICT = 'conflict'


@dataclass(frozen=True)
class Proposal:
    id: str
    conversation_id: str
    approval_token: str = field(repr=False)
    guest: Guest
    conditions: BookingConditions
    created_at: datetime
    expires_at: datetime
    reservation_id: str | None = None
    reservation_version: int | None = None
    status: ProposalStatus = ProposalStatus.PENDING
    result: Reservation | None = None


def overlaps(left: BookingConditions, right: BookingConditions) -> bool:
    """終了と次の開始が一致する予約は重複しない。"""
    return left.start < right.end and right.start < left.end


def choose_table(tables: list[Table], reservations: list[Reservation], conditions: BookingConditions,
                 exclude_reservation_id: str | None = None) -> Table | None:
    """指定席種で全員を収容できる最小の空き卓を選ぶ。"""
    for table in sorted(tables, key=lambda t: (t.capacity, t.id)):
        if table.seat_type != conditions.seat_type or table.capacity < conditions.party_size:
            continue
        if not any(r.id != exclude_reservation_id and r.table_id == table.id
                   and overlaps(r.conditions, conditions) for r in reservations):
            return table
    return None
