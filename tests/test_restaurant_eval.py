"""既知の誤答で、評価器の偽合格・偽不合格を確認する。"""
import json
from pathlib import Path
import unittest

from google.adk.evaluation.eval_case import IntermediateData, Invocation
from google.adk.evaluation.eval_metrics import EvalStatus
from google.adk.evaluation.eval_set import EvalSet
from google.genai import types

from evals.metrics import evaluate_dimension

RULES = {'required': ['未確定'], 'forbidden': ['確定しました'],
         'tools': [{'name': 'propose_reservation', 'args': {'party_size': 2}}],
         'allowed_tools': ['propose_reservation'],
         'outcomes': [{'name': 'propose_reservation', 'fields': {'status': 'proposed'}}]}


def invocation(text='未確定です。', name='propose_reservation', size=2, status='proposed'):
    return Invocation(user_content=types.Content(role='user', parts=[]),
                      final_response=types.Content(role='model', parts=[types.Part.from_text(text=text)]),
                      intermediate_data=IntermediateData(
                          tool_uses=[types.FunctionCall(name=name, args={'party_size': size})],
                          tool_responses=[types.FunctionResponse(name=name, response={'status': status})]))


class ReservationEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.expected = invocation(json.dumps(RULES, ensure_ascii=False))

    def status(self, actual, dimension):
        return evaluate_dimension([actual], [self.expected], dimension).overall_eval_status

    def test_correct_result_passes_all_three_dimensions(self):
        for dimension in ('response', 'tools', 'outcome'):
            self.assertEqual(self.status(invocation(), dimension), EvalStatus.PASSED)

    def test_known_faults_fail_relevant_dimension(self):
        faults = [
            ('response', invocation('未確定のはずですが確定しました')),
            ('response', invocation('')),
            ('tools', invocation(name='confirm_proposal')),
            ('tools', invocation(size=4)),
            ('outcome', invocation(status='confirmed')),
            ('outcome', invocation(text='未確定 approval_token')),
        ]
        for dimension, actual in faults:
            with self.subTest(dimension=dimension):
                self.assertEqual(self.status(actual, dimension), EvalStatus.FAILED)

    def test_missing_tool_result_or_turn_is_not_a_pass(self):
        actual = invocation()
        actual.intermediate_data = None
        self.assertEqual(self.status(actual, 'tools'), EvalStatus.FAILED)
        self.assertEqual(self.status(actual, 'outcome'), EvalStatus.FAILED)
        self.assertEqual(evaluate_dimension([], [self.expected], 'response').overall_eval_status, EvalStatus.FAILED)

    def test_one_failed_turn_fails_entire_case(self):
        result = evaluate_dimension([invocation(), invocation('確定しました')], [self.expected, self.expected], 'response')
        self.assertEqual(result.overall_score, 0)
        self.assertEqual([row.score for row in result.per_invocation_results], [1, 0])

    def test_incorrect_weekday_is_not_a_pass(self):
        for text in ('2026年10月9日（土）', '2026-10-09 木曜日', '2026/10/09 (日)', '2026-13-09（月）'):
            with self.subTest(date=text):
                self.assertEqual(self.status(invocation(text + '、未確定です。'), 'response'), EvalStatus.FAILED)
        for text in ('2026年10月9日（金）', '2026-10-09 金曜日', '2026/10/09 (金)'):
            with self.subTest(date=text):
                self.assertEqual(self.status(invocation(text + '、未確定です。'), 'response'), EvalStatus.PASSED)

    def test_extra_call_with_wrong_arguments_is_not_a_pass(self):
        actual = invocation()
        actual.intermediate_data.tool_uses.append(types.FunctionCall(name='propose_reservation', args={'party_size': 6}))
        self.assertEqual(self.status(actual, 'tools'), EvalStatus.FAILED)

    def test_omitted_optional_arguments_use_production_defaults(self):
        rules = {**RULES, 'tools': [{'name': 'search_availability', 'args': {'expand_time': False, 'alternate_seat': ''}}],
                 'allowed_tools': ['search_availability']}
        expected = invocation(json.dumps(rules, ensure_ascii=False))
        actual = invocation(name='search_availability')
        result = evaluate_dimension([actual], [expected], 'tools')
        self.assertEqual(result.overall_eval_status, EvalStatus.PASSED)

    def test_proposal_contract_requires_date_duration_and_window_disclaimer(self):
        root = Path(__file__).resolve().parents[1] / 'evals'
        dataset = json.loads((root / 'restaurant_development.evalset.json').read_text())
        expected = Invocation.model_validate(dataset['eval_cases'][0]['conversation'][0])
        valid = '2026-10-09 18:00、2名、通常テーブル、90分利用。未確定です。窓際は希望として受け付けますが確約できません。'
        self.assertEqual(evaluate_dimension([invocation(valid)], [expected], 'response').overall_eval_status, EvalStatus.PASSED)
        for incomplete in (valid.replace('2026-10-09 ', ''), valid.replace('90分利用。', ''),
                           valid.replace('窓際は希望として受け付けますが確約できません。', '窓際希望あり。')):
            with self.subTest(response=incomplete):
                self.assertEqual(evaluate_dimension([invocation(incomplete)], [expected], 'response').overall_eval_status, EvalStatus.FAILED)

    def test_full_search_accepts_canonical_message_and_rejects_claimed_availability(self):
        root = Path(__file__).resolve().parents[1] / 'evals'
        dataset = json.loads((root / 'restaurant_development.evalset.json').read_text())
        case = next(case for case in dataset['eval_cases'] if case['eval_id'] == 'no_relaxation')
        expected = Invocation.model_validate(case['conversation'][0])
        actual = invocation('希望の条件（2026-10-09、19:00、4名、個室）では空席がありません。代替時刻として20:00に空きがあります。',
                            name='search_availability', size=4, status='available')
        actual.intermediate_data.tool_uses[0].args = {'date': '2026-10-09', 'time': '19:00', 'party_size': 4, 'seat_type': 'private'}
        actual.intermediate_data.tool_responses[0].response['requested_available'] = False
        for dimension in ('response', 'tools', 'outcome'):
            self.assertEqual(evaluate_dimension([actual], [expected], dimension).overall_eval_status, EvalStatus.PASSED)
        actual.final_response.parts[0].text = '希望の19:00は空いています。20:00にも空きがあります。'
        self.assertEqual(evaluate_dimension([actual], [expected], 'response').overall_eval_status, EvalStatus.FAILED)

    def test_datasets_validate_and_have_disjoint_ids(self):
        root = Path(__file__).resolve().parents[1] / 'evals'
        dev = EvalSet.model_validate_json((root / 'restaurant_development.evalset.json').read_text())
        holdout = EvalSet.model_validate_json((root / 'restaurant_holdout.evalset.json').read_text())
        self.assertFalse({c.eval_id for c in dev.eval_cases} & {c.eval_id for c in holdout.eval_cases})
        for case in dev.eval_cases + holdout.eval_cases:
            for turn in case.conversation:
                rules = json.loads(turn.final_response.parts[0].text)
                self.assertEqual(set(rules), set(RULES))

    def test_agent_uses_production_tools_without_confirmation_tool(self):
        from evals.restaurant_agent.agent import root_agent, service
        self.assertEqual(root_agent.name, 'restaurant_consultant')
        self.assertEqual([tool.__name__ for tool in root_agent.tools],
                         ['search_availability', 'find_reservations', 'propose_reservation', 'propose_reservation_change'])
        self.assertEqual(len(service.repository.reservations()), 3)
        self.assertEqual(service.clock.now().isoformat(), '2026-10-08T09:00:00+09:00')
