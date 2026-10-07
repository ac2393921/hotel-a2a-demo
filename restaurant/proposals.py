"""照合と提案のユースケース。予約確定の副作用は持たない。"""
import secrets
from dataclasses import replace
from datetime import timedelta

from restaurant.domain import BookingConditions, Guest, Proposal, ProposalStatus, SeatType, choose_table
from restaurant.ports import Clock, ReservationRepository


def conditions_summary(conditions: BookingConditions) -> str:
    seat = '個室' if conditions.seat_type == SeatType.PRIVATE else '通常テーブル'
    window = '窓際は希望として受付けますが確約できません。' if conditions.window_preference else '窓際の指定はありません。'
    return (f'{conditions.start:%Y-%m-%d %H:%M}、{conditions.party_size}名、{seat}、'
            f'90分利用です。{window}まだ予約は確定していません。')


def public_proposal(proposal: Proposal) -> dict:
    """LLM・画面へ渡せる内容。承認tokenと照合情報は含めない。"""
    return {'status': 'proposed', 'proposal_id': proposal.id,
            'expires_at': proposal.expires_at.isoformat(),
            'summary': conditions_summary(proposal.conditions), 'approval_required': True}


class ProposalService:
    def __init__(self, repository: ReservationRepository, clock: Clock):
        self.repository = repository
        self.clock = clock
        self._matched: dict[str, tuple[Guest, frozenset[str]]] = {}

    @staticmethod
    def _valid_conversation(conversation_id: str) -> bool:
        return isinstance(conversation_id, str) and 1 <= len(conversation_id) <= 200

    def find(self, conversation_id: str, guest: Guest) -> dict:
        if not self._valid_conversation(conversation_id):
            return {'status': 'invalid_request', 'message': '会話IDが不正です。'}
        reservations = [r for r in self.repository.reservations() if r.guest == guest]
        self._matched[conversation_id] = (guest, frozenset(r.id for r in reservations))
        if not reservations:
            return {'status': 'not_found', 'message': '該当する予約がありません。', 'reservations': []}
        return {'status': 'clarification_required' if len(reservations) > 1 else 'available',
                'message': '変更する予約を選んでください。' if len(reservations) > 1 else '予約が見つかりました。',
                'reservations': [{'reservation_id': r.id, 'date': r.conditions.start.strftime('%Y-%m-%d'),
                                  'time': r.conditions.start.strftime('%H:%M'),
                                  'party_size': r.conditions.party_size, 'seat_type': r.conditions.seat_type.value}
                                 for r in sorted(reservations, key=lambda r: (r.conditions.start, r.id))]}

    async def propose(self, conversation_id: str, guest: Guest, conditions: BookingConditions,
                      reservation_id: str | None = None) -> Proposal | dict:
        if not self._valid_conversation(conversation_id):
            return {'status': 'invalid_request', 'message': '会話IDが不正です。'}
        now = self.clock.now()
        try:
            conditions.validate(now)
        except ValueError as error:
            return {'status': 'invalid_request', 'message': str(error)}
        async with self.repository.transaction():
            original = None
            if reservation_id is not None:
                match = self._matched.get(conversation_id)
                original = self.repository.get_reservation(reservation_id)
                if (match is None or match[0] != guest or reservation_id not in match[1]
                        or original is None or original.guest != guest):
                    return {'status': 'not_found', 'message': '照合済みの対象予約を選んでください。'}
            table = choose_table(self.repository.tables(), self.repository.reservations(),
                                 conditions, reservation_id)
            if table is None:
                return {'status': 'unavailable', 'message': 'その条件は満席です。候補を再検索してください。'}
            proposal = Proposal(secrets.token_urlsafe(24), conversation_id, secrets.token_urlsafe(32),
                                guest, conditions, now, now + timedelta(minutes=10),
                                original.id if original else None, original.version if original else None)
            self.repository.save_proposal(proposal)
            return proposal

    async def reject(self, conversation_id: str, proposal_id: str, approval_token: str) -> dict:
        async with self.repository.transaction():
            proposal = self.repository.get_proposal(proposal_id)
            if (proposal is None or proposal.conversation_id != conversation_id
                    or not isinstance(approval_token, str)
                    or not secrets.compare_digest(proposal.approval_token, approval_token)):
                return {'status': 'not_found', 'message': '対象の提案がありません。'}
            if proposal.status == ProposalStatus.REJECTED:
                return {'status': 'rejected', 'message': '提案を取り下げました。予約は変更していません。'}
            if proposal.status != ProposalStatus.PENDING:
                return {'status': 'conflict', 'message': 'この提案はすでに処理済みです。'}
            if proposal.expires_at <= self.clock.now():
                return {'status': 'expired', 'message': '提案の期限が切れています。'}
            self.repository.save_proposal(replace(proposal, status=ProposalStatus.REJECTED))
            return {'status': 'rejected', 'message': '提案を取り下げました。予約は変更していません。'}
