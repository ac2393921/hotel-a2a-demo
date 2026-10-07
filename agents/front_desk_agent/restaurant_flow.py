"""Front Deskの予約相談とサーバー内承認資格。業務判断は持たない。"""
import json

from agents.front_desk_agent.agent import DepartmentCall, _agent_card_url

# tokenはADKの会話state・モデル入力・ブラウザーへ置かない。
credentials: dict[str, tuple[str, str]] = {}


def restaurant_call(payload: dict) -> DepartmentCall:
    return DepartmentCall(name='restaurant_agent', display_name='Restaurant Agent',
                          description='予約相談と明示承認を担当するRestaurant Agent',
                          agent_card=_agent_card_url('RESTAURANT_AGENT_BASE_URL', 8003),
                          request_text=json.dumps(payload, ensure_ascii=False))


def consultation_call(session_id: str, message: str, state: dict) -> DepartmentCall:
    return restaurant_call({'version':2,'action':'consult','conversation_id':session_id,'message':message,
                            'expand_time_permitted': state.get('restaurant_expand_time_permitted',False),
                            'alternate_seat_permitted':state.get('restaurant_alternate_seat_permitted',False)})


def decision_call(session_id: str, decision: dict) -> DepartmentCall | None:
    saved = credentials.get(session_id)
    if saved is None or decision.get('proposal_id') != saved[0] or decision.get('decision') not in {'approve','reject'}:
        return None
    return restaurant_call({'version':2,'action':'confirm_proposal' if decision['decision']=='approve' else 'reject_proposal',
                            'conversation_id':session_id,'proposal_id':saved[0],'approval_token':saved[1]})


def safe_trace(call: DepartmentCall) -> str:
    if call.name != 'restaurant_agent':
        return call.request_text
    return 'Restaurantへの依頼（ゲスト照合情報と承認資格は非表示）'
