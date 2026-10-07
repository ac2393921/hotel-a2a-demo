"""ゲストの構造化承認とサーバー資格の隔離を検証する。"""
import json
import unittest
from types import SimpleNamespace
from agents.front_desk_agent.agent import FrontDeskCoordinator, PENDING_RESTAURANT_PROPOSAL_KEY
from agents.front_desk_agent.restaurant_flow import credentials, decision_call, consultation_call, safe_trace
from agents.front_desk_agent.intent import validate_intent_output


class GuestFlowTests(unittest.TestCase):
    def setUp(self):
        credentials.clear()
        self.ctx = SimpleNamespace(session=SimpleNamespace(id='c',state={'restaurant_v2_active':True}))

    def test_proposal_token_stays_out_of_state_and_display(self):
        text, delta = FrontDeskCoordinator._handle_restaurant_response(self.ctx,json.dumps(
            {'status':'proposed','proposal_id':'p','approval_token':'private-token','summary':'明日20時、4名、個室、90分。窓際非確約。'}))
        self.assertNotIn('private-token',text)
        self.assertNotIn('private-token',json.dumps(delta))
        self.assertNotIn('private-token',json.dumps(self.ctx.session.state))
        call = decision_call('c',{'decision':'approve','proposal_id':'p'})
        self.assertEqual(json.loads(call.request_text)['approval_token'],'private-token')
        self.assertNotIn('private-token',safe_trace(call))
        self.assertIsNone(decision_call('other',{'decision':'approve','proposal_id':'p'}))
        self.assertIsNone(decision_call('c',{'decision':'approve','proposal_id':'old'}))

    def test_conflict_clears_pending_and_preserves_reconsultation(self):
        credentials['c']=('p','token')
        self.ctx.session.state[PENDING_RESTAURANT_PROPOSAL_KEY]='p'
        text,delta=FrontDeskCoordinator._handle_restaurant_response(self.ctx,json.dumps(
            {'status':'conflict','message':'満席です。元予約は維持しています。','candidates':[{'date':'2026-10-08','time':'20:30','party_size':4,'seat_type':'private'}]}))
        self.assertIn('20:30',text)
        self.assertNotIn('c',credentials)
        self.assertFalse(self.ctx.session.state.get(PENDING_RESTAURANT_PROPOSAL_KEY))
        self.assertTrue(self.ctx.session.state['restaurant_v2_active'])

    def test_new_reservation_does_not_require_old_reservation_time(self):
        result=validate_intent_output(json.dumps({'decision':'dispatch','requests':[{
            'department':'restaurant_agent','operation':'consult_restaurant','details':'予約したい',
            'reservation_time':'','requested_time':''}],'response_message':''}))
        self.assertEqual(result.decision,'dispatch')

    def test_permission_flags_come_from_server_state(self):
        call=consultation_call('c','別の席も探して',{})
        payload=json.loads(call.request_text)
        self.assertFalse(payload['alternate_seat_permitted'])
        self.assertFalse(payload['expand_time_permitted'])

    def test_ui_decision_requires_proposal_and_rejects_token_input(self):
        from hotel_ui.app import GuestMessage
        from pydantic import ValidationError
        for payload in [{'text':'はい','decision':'approve'}, {'text':'はい','approval_token':'token'}]:
            with self.assertRaises(ValidationError): GuestMessage.model_validate(payload)
        message=GuestMessage(text='承認',decision='approve',proposal_id='p')
        self.assertEqual(message.proposal_id,'p')

class StructuredDecisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirmation_bypasses_intent_model_and_hides_token(self):
        from unittest.mock import patch, AsyncMock
        from google.adk.events import Event
        from google.genai import types
        import agents.front_desk_agent.agent as front_desk
        from tests.test_front_desk_failures import FakeParallelAgent
        credentials['structured-session']=('p','server-token')
        ctx=SimpleNamespace(invocation_id='invocation',branch='main',user_content=None,
                            session=SimpleNamespace(id='structured-session',state={
                                'restaurant_v2_active':True,'restaurant_structured_decision':{'decision':'approve','proposal_id':'p'}}))
        calls=[]
        class Remote:
            async def run_async(self,_ctx):
                yield Event(author='restaurant_agent',content=types.Content(role='model',parts=[types.Part.from_text(text=json.dumps(
                    {'status':'confirmed','message':'予約を確定しました。','date':'2026-10-08','time':'20:00','party_size':4,'seat_type':'private'}))]))
            async def cleanup(self): pass
        def create(call):
            calls.append(call)
            return Remote()
        with patch.object(front_desk,'_create_remote_agent',side_effect=create), patch.object(front_desk,'ParallelAgent',FakeParallelAgent), patch.object(front_desk,'intent_agent') as intent:
            events=[e async for e in front_desk.root_agent._run_async_impl(ctx)]
            intent.run_async.assert_not_called()
        self.assertEqual(json.loads(calls[0].request_text)['action'],'confirm_proposal')
        self.assertTrue(all('server-token' not in e.model_dump_json() for e in events))
        self.assertIn('予約を確定しました',events[-1].content.parts[0].text)


class InvalidContinuationTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_classification_reconsults_without_confirmation(self):
        from unittest.mock import patch
        from google.adk.events import Event
        from google.genai import types
        import agents.front_desk_agent.agent as front_desk
        from tests.test_front_desk_failures import FakeParallelAgent
        ctx = SimpleNamespace(invocation_id='invalid', branch='main',
                              user_content=types.Content(role='user', parts=[types.Part.from_text(text='変更案を相談したい')]),
                              session=SimpleNamespace(id='invalid', state={'restaurant_v2_active':True}))
        class InvalidIntent:
            name = 'front_desk_intent_agent'
            async def run_async(self, _ctx):
                yield Event(author=self.name, content=types.Content(role='model', parts=[types.Part.from_text(text='{"approved":true}')]))
        class Remote:
            async def run_async(self, _ctx):
                yield Event(author='restaurant_agent', content=types.Content(role='model', parts=[types.Part.from_text(text='{"status":"clarification_required","message":"条件を確認します。"}')]))
            async def cleanup(self): pass
        calls = []
        def create(call):
            calls.append(call)
            return Remote()
        with patch.object(front_desk, 'intent_agent', InvalidIntent()), patch.object(front_desk, '_create_remote_agent', side_effect=create), patch.object(front_desk, 'ParallelAgent', FakeParallelAgent):
            events = [event async for event in front_desk.root_agent._run_async_impl(ctx)]
        self.assertEqual(len(calls), 1)
        self.assertEqual(json.loads(calls[0].request_text)['action'], 'consult')
        self.assertNotIn('approval_token', calls[0].request_text)
        self.assertIn('条件を確認', events[-1].content.parts[0].text)
