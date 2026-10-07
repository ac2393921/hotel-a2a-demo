"""明示承認に紐付く提案の原子的な確定。"""
import secrets
from dataclasses import replace

from restaurant.availability import AvailabilityService
from restaurant.domain import ProposalStatus, Reservation, choose_table
from restaurant.ports import Clock, ReservationRepository


def reservation_result(reservation: Reservation) -> dict:
    conditions = reservation.conditions
    return {'status': 'confirmed', 'message': '予約を確定しました。',
            'reservation_id': reservation.id, 'date': conditions.start.strftime('%Y-%m-%d'),
            'time': conditions.start.strftime('%H:%M'), 'party_size': conditions.party_size,
            'seat_type': conditions.seat_type.value, 'duration_minutes': 90,
            'window_preference': conditions.window_preference, 'window_guaranteed': False}


class ConfirmationService:
    def __init__(self, repository: ReservationRepository, clock: Clock):
        self.repository = repository
        self.clock = clock

    async def confirm(self, conversation_id: str, proposal_id: str, approval_token: str) -> dict:
        if any(not isinstance(v, str) or not 1 <= len(v) <= 200 for v in [conversation_id, proposal_id, approval_token]):
            return {'status': 'invalid_request', 'message': '承認の依頼形式を確認してください。'}
        async with self.repository.transaction():
            proposal = self.repository.get_proposal(proposal_id)
            if (proposal is None or proposal.conversation_id != conversation_id
                    or not secrets.compare_digest(proposal.approval_token.encode(), approval_token.encode())):
                return {'status': 'not_found', 'message': '有効な対象提案がありません。'}
            if proposal.status == ProposalStatus.CONFIRMED and proposal.result is not None:
                return reservation_result(proposal.result)
            if proposal.status != ProposalStatus.PENDING:
                return {'status': 'conflict', 'message': '処理済みの提案は再確定できません。'}
            now = self.clock.now()
            if proposal.expires_at <= now:
                return {'status': 'expired', 'message': '提案の期限が切れています。再度相談してください。'}
            try:
                proposal.conditions.validate(now)
            except ValueError:
                return {'status': 'expired', 'message': '予約時刻を過ぎています。再度相談してください。'}
            original = None
            if proposal.reservation_id is not None:
                original = self.repository.get_reservation(proposal.reservation_id)
                if original is None or original.guest != proposal.guest or original.version != proposal.reservation_version:
                    self.repository.save_proposal(replace(proposal, status=ProposalStatus.CONFLICT))
                    return {'status': 'conflict', 'message': '元の予約が変更されています。照合して新しい提案を選んでください。'}
            table = choose_table(self.repository.tables(), self.repository.reservations(),
                                 proposal.conditions, proposal.reservation_id)
            if table is None:
                self.repository.save_proposal(replace(proposal, status=ProposalStatus.CONFLICT))
                alternatives = AvailabilityService(self.repository, self.clock).search(
                    proposal.conditions, exclude_reservation_id=proposal.reservation_id)
                return {'status': 'conflict', 'message': '承認時点で満席になりました。元の予約は維持しています。再度候補を選んでください。',
                        'candidates': [{'date': c.start.strftime('%Y-%m-%d'), 'time': c.start.strftime('%H:%M'),
                                        'party_size': c.party_size, 'seat_type': c.seat_type.value}
                                       for c in alternatives.candidates]}
            reservation = Reservation(original.id if original else secrets.token_urlsafe(24),
                                      proposal.guest, table.id, proposal.conditions,
                                      original.version + 1 if original else 1)
            self.repository.save_reservation(reservation)
            self.repository.save_proposal(replace(proposal, status=ProposalStatus.CONFIRMED, result=reservation))
            return reservation_result(reservation)
