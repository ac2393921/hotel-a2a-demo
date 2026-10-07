"""評価専用ポートに一致するAgent Cardで、製品のRestaurantを公開する。"""
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from agents.restaurant_agent.agent import root_agent

a2a_app = to_a2a(root_agent, host='127.0.0.1', port=8803)
