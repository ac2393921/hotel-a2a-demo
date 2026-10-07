"""LLM向け入力アダプター。会話と許可はサーバーが束縛する。"""
from datetime import datetime
import re

from restaurant.availability import AvailabilityService
from restaurant.domain import BookingConditions, Guest, Proposal, SeatType
from restaurant.proposals import ProposalService, public_proposal


class ReservationTools:
    def __init__(self, conversation_id: str, availability: AvailabilityService, proposals: ProposalService):
        self.conversation_id = conversation_id
        self.availability = availability
        self.proposals = proposals
        self.expand_time_permitted = False
        self.alternate_seat_permitted = False
        self.last_result: dict | None = None
        self.pending: Proposal | None = None

    def _conditions(self, date: str, time: str, party_size: int, seat_type: str, window_preference: bool = False):
        if not isinstance(date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
            raise ValueError('日付はYYYY-MM-DDで指定してください。')
        if not isinstance(time, str) or not re.fullmatch(r'\d{2}:\d{2}', time):
            raise ValueError('時刻はHH:MMで指定してください。')
        start = datetime.fromisoformat(f'{date}T{time}').replace(tzinfo=self.availability.clock.now().tzinfo)
        conditions = BookingConditions(start, party_size, SeatType(seat_type), window_preference)
        conditions.validate(self.availability.clock.now())
        return conditions

    def _record(self, result: dict) -> dict:
        self.last_result = result
        return result

    def search_availability(self, date: str, time: str, party_size: int, seat_type: str,
                            expand_time: bool = False, alternate_seat: str = '') -> dict:
        """日付・時刻・人数・席種で空席を検索する。許可なしに条件を緩めない。"""
        try:
            if (expand_time and not self.expand_time_permitted) or (alternate_seat and not self.alternate_seat_permitted):
                return self._record({'status': 'clarification_required', 'message': '席種変更や時間範囲拡大の許可を確認してください。'})
            conditions = self._conditions(date, time, party_size, seat_type)
            result = self.availability.search(conditions, expand_time=expand_time,
                                             alternate_seat=SeatType(alternate_seat) if alternate_seat else None)
            return self._record({'status': result.status, 'message': result.message,
                                 'requested_available': result.requested_available,
                                 'relaxation_required': result.relaxation_required,
                                 'candidates': [{'date': c.start.strftime('%Y-%m-%d'), 'time': c.start.strftime('%H:%M'),
                                                 'party_size': c.party_size, 'seat_type': c.seat_type.value}
                                                for c in result.candidates]})
        except (ValueError, TypeError):
            return self._record({'status': 'invalid_request', 'message': '予約条件を確認してください。'})

    def find_reservations(self, room_number: str, guest_name: str) -> dict:
        """部屋番号と氏名を照合する。複数予約なら対象を選んでもらう。"""
        try:
            return self._record(self.proposals.find(self.conversation_id, Guest(room_number, guest_name)))
        except (ValueError, TypeError):
            return self._record({'status': 'invalid_request', 'message': '部屋番号と氏名を確認してください。'})

    async def _propose(self, date, time, party_size, seat_type, room_number, guest_name, window_preference, reservation_id=None):
        try:
            conditions = self._conditions(date, time, party_size, seat_type, window_preference)
            result = await self.proposals.propose(self.conversation_id, Guest(room_number, guest_name), conditions, reservation_id)
            if isinstance(result, Proposal):
                self.pending = result
                return self._record(public_proposal(result))
            return self._record(result)
        except (ValueError, TypeError):
            return self._record({'status': 'invalid_request', 'message': '予約条件とゲスト情報を確認してください。'})

    async def propose_reservation(self, date: str, time: str, party_size: int, seat_type: str,
                                  room_number: str, guest_name: str, window_preference: bool = False) -> dict:
        """ゲストが選んだ新規予約の条件を提案する。予約は確定しない。"""
        return await self._propose(date, time, party_size, seat_type, room_number, guest_name, window_preference)

    async def propose_reservation_change(self, reservation_id: str, date: str, time: str, party_size: int,
                                         seat_type: str, room_number: str, guest_name: str,
                                         window_preference: bool = False) -> dict:
        """照合してゲストが選んだ予約の変更案を作る。元の予約は維持する。"""
        if not reservation_id:
            return self._record({'status': 'invalid_request', 'message': '変更対象を選んでください。'})
        return await self._propose(date, time, party_size, seat_type, room_number, guest_name, window_preference, reservation_id)

    def functions(self):
        return [self.search_availability, self.find_reservations,
                self.propose_reservation, self.propose_reservation_change]
