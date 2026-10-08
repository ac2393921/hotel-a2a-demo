"""製品と同じRestaurant相談Agentを固定時刻・架空データで単体評価する。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from agents.restaurant_agent.consultation import ConsultationService
from agents.restaurant_agent.tools import ReservationTools


class EvaluationClock:
    def now(self):
        return datetime(2026, 10, 8, 9, 0, tzinfo=ZoneInfo("Asia/Tokyo"))


service = ConsultationService(clock=EvaluationClock())
tools = ReservationTools("restaurant-agent-eval", service.availability, service.proposals)
root_agent = service.create_agent(tools)
# 製品は各発話に現在時刻を付ける。評価は同じ情報を固定して渡す。
root_agent.instruction += f"\nホテル現地日時: {service.clock.now().isoformat()}"
