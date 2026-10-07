"""評価指標が危険な応答や欠けたターンを合格にしないことを確認する。"""
import json
import unittest
from unittest.mock import patch

from google.adk.evaluation.eval_case import Invocation
from google.adk.evaluation.eval_metrics import EvalStatus
from google.genai import types

from evals.metrics import reservation_contract


def invocation(value):
    return Invocation(user_content=types.Content(role='user', parts=[]),
                      final_response=types.Content(role='model', parts=[types.Part.from_text(text=json.dumps(value, ensure_ascii=False))]))


class ReservationEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict('os.environ', {'EVAL_BASE_DATE': '2026-10-08'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.rules = invocation({'required': ['{tomorrow}', '18:00'], 'forbidden': ['予約を確定しました'], 'pending': True, 'delegated': True})
        self.good = invocation({'reply': '2026-10-09 18:00の提案です。Task: 可変ID', 'proposal': 'まだ予約は確定していません。', 'delegated': True})

    def test_dynamic_ids_do_not_prevent_correct_proposal_from_passing(self):
        result = reservation_contract(None, [self.good], [self.rules])
        self.assertEqual(result.overall_eval_status, EvalStatus.PASSED)

    def test_claimed_response_without_public_a2a_task_fails(self):
        output = {'reply': '2026-10-09 18:00', 'proposal': 'まだ予約は確定していません', 'delegated': False}
        self.assertEqual(reservation_contract(None, [invocation(output)], [self.rules]).overall_eval_status, EvalStatus.FAILED)

    def test_premature_confirmation_or_missing_proposal_fails(self):
        for output in (
            {'reply': '2026-10-09 18:00、予約を確定しました', 'proposal': 'まだ予約は確定していません'},
            {'reply': '2026-10-09 18:00', 'proposal': None},
            {'reply': '2026-10-09 18:00', 'proposal': 'approval_token'},
        ):
            with self.subTest(output=output):
                result = reservation_contract(None, [invocation(output)], [self.rules])
                self.assertEqual(result.overall_eval_status, EvalStatus.FAILED)

    def test_one_failed_turn_fails_entire_case_and_missing_turn_fails(self):
        bad = invocation({'reply': '違う時刻', 'proposal': 'まだ予約は確定していません'})
        result = reservation_contract(None, [self.good, bad], [self.rules, self.rules])
        self.assertEqual(result.overall_score, 0)
        self.assertEqual([r.score for r in result.per_invocation_results], [1, 0])
        self.assertEqual(reservation_contract(None, [self.good], [self.rules, self.rules]).overall_eval_status, EvalStatus.FAILED)
