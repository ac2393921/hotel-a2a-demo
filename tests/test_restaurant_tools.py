"""LLMのtoolと構造化受付の権限境界を検証する。"""
import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from agents.restaurant_agent.consultation import ConsultationService
from agents.restaurant_agent.tools import ReservationTools
from restaurant.memory import demo_repository
from restaurant.availability import AvailabilityService
from restaurant.proposals import ProposalService


class FixedClock:
    def now(self):
        return datetime(2026, 10, 7, 10, tzinfo=ZoneInfo('Asia/Tokyo'))


class ProposalModel(BaseLlm):
    model: str = 'test-model'

    async def generate_content_async(self, llm_request, stream=False):
        if not any(p.function_response for p in llm_request.contents[-1].parts or []):
            part = types.Part.from_function_call(name='propose_reservation', args={
                'date': '2026-10-08', 'time': '20:00', 'party_size': 4,
                'seat_type': 'table', 'room_number': '101', 'guest_name': 'デモ花子'})
        else:
            part = types.Part.from_text(text='予約案をご確認ください。')
        yield LlmResponse(content=types.Content(role='model', parts=[part]))


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FixedClock()
        self.repo = demo_repository(self.clock)
        self.tools = ReservationTools('bound-conversation', AvailabilityService(self.repo, self.clock),
                                      ProposalService(self.repo, self.clock))

    async def test_tools_have_no_confirmation_or_conversation_parameters(self):
        import inspect
        functions = self.tools.functions()
        self.assertEqual(len(functions), 4)
        for function in functions:
            self.assertNotIn('confirm', function.__name__)
            self.assertNotIn('conversation_id', inspect.signature(function).parameters)
            self.assertNotIn('approval_token', inspect.signature(function).parameters)

    async def test_relaxation_requires_server_permission(self):
        result = self.tools.search_availability('2026-10-08','19:00',4,'private',expand_time=True)
        self.assertEqual(result['status'], 'clarification_required')

    async def test_tool_proposal_hides_token(self):
        result = await self.tools.propose_reservation('2026-10-08','20:00',4,'table','101','デモ花子')
        self.assertEqual(result['status'], 'proposed')
        self.assertNotIn('approval_token', result)
        self.assertEqual(self.tools.pending.conversation_id, 'bound-conversation')

    async def test_runner_uses_tool_and_emits_server_proposal(self):
        service = ConsultationService(self.repo, self.clock, ProposalModel())
        result = await service.handle({'version':2,'action':'consult','conversation_id':'c','message':'予約したい'})
        self.assertEqual(result['status'], 'proposed')
        self.assertIn('approval_token', result)
        self.assertEqual(len(self.repo.reservations()), 3)
        tools, runner, session_id = service._conversations['c']
        session = await runner.session_service.get_session(app_name='restaurant', user_id='demo', session_id=session_id)
        event_text = '\n'.join(e.model_dump_json() for e in session.events)
        self.assertNotIn(result['approval_token'], event_text)

    async def test_invalid_envelope_never_invokes_model(self):
        service = ConsultationService(self.repo,self.clock,ProposalModel())
        for payload in [{'version':2,'action':'confirm_proposal','conversation_id':'c','message':'はい'},
                        {'version':True,'action':'consult','conversation_id':'c','message':'予約したい'},
                        {'version':2,'action':'consult','conversation_id':'c','message':'予約したい','approved':True}]:
            self.assertEqual((await service.handle(payload))['status'], 'invalid_request')
        self.assertEqual(service._conversations, {})

    async def test_version_two_proposal_over_public_a2a(self):
        from unittest.mock import patch
        from uuid import uuid4
        import httpx
        from a2a.client import ClientConfig, ClientFactory
        from a2a.types import Message, Part, SendMessageRequest
        from agents.restaurant_agent.agent import a2a_app
        service = ConsultationService(self.repo, self.clock, ProposalModel())
        with patch('agents.restaurant_agent.agent.consultation_service', service):
            async with a2a_app.router.lifespan_context(a2a_app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=a2a_app), base_url='http://localhost:8003') as http:
                    card = (await http.get('/.well-known/agent-card.json')).json()
                    self.assertIn('空席検索', card['description'])
                    client = await ClientFactory(ClientConfig(httpx_client=http)).create_from_url('http://localhost:8003')
                    request = SendMessageRequest(message=Message(message_id=str(uuid4()), role='ROLE_USER', parts=[Part(text=json.dumps(
                        {'version':2,'action':'consult','conversation_id':'a2a-session','message':'予約したい'}))]))
                    answers = []
                    async for event in client.send_message(request):
                        if event.WhichOneof('payload') == 'artifact_update':
                            answers.extend(p.text for p in event.artifact_update.artifact.parts if p.text)
                    await client.close()
                    self.assertTrue(any('"status": "proposed"' in answer for answer in answers))
                    self.assertEqual(len(self.repo.reservations()), 3)
