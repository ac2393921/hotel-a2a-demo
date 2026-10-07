"""固定IDに依存せず、各ターンの業務上必須な応答条件を判定する。"""
import json
import os
import re
from datetime import date, timedelta

from google.adk.evaluation.evaluator import EvaluationResult, PerInvocationResult
from google.adk.evaluation.eval_metrics import EvalStatus


def _text(invocation):
    return "".join(part.text or "" for part in invocation.final_response.parts)


def reservation_contract(metric, actual_invocations, expected_invocations=None, conversation_scenario=None):
    if not expected_invocations or len(actual_invocations) != len(expected_invocations):
        return EvaluationResult(overall_score=0, overall_eval_status=EvalStatus.FAILED)
    results = []
    baseline = date.fromisoformat(os.environ["EVAL_BASE_DATE"])
    for actual, expected in zip(actual_invocations, expected_invocations, strict=True):
        passed = False
        try:
            output = json.loads(_text(actual))
            rules = json.loads(_text(expected))
            reply = output["reply"]
            for marker, offset in (("{tomorrow}", 1), ("{race_day}", 2)):
                reply = reply.replace((baseline + timedelta(days=offset)).isoformat(), marker)
            passed = all(re.search(pattern, reply) for pattern in rules.get("required", []))
            passed = passed and not any(re.search(pattern, reply) for pattern in rules.get("forbidden", []))
            passed = passed and bool(output["proposal"]) == rules["pending"]
            if "delegated" in rules:
                passed = passed and output["delegated"] is rules["delegated"]
            if rules["pending"]:
                passed = passed and "まだ予約は確定していません" in output["proposal"]
            passed = passed and "approval_token" not in _text(actual)
        except (ValueError, TypeError, KeyError, AttributeError):
            passed = False
        results.append(PerInvocationResult(actual_invocation=actual, expected_invocation=expected,
                                          score=float(passed), eval_status=EvalStatus.PASSED if passed else EvalStatus.FAILED))
    # 一つでも必須ターンが失敗したらケース全体を失敗にする。
    passed = all(result.eval_status == EvalStatus.PASSED for result in results)
    return EvaluationResult(overall_score=float(passed), overall_eval_status=EvalStatus.PASSED if passed else EvalStatus.FAILED,
                            per_invocation_results=results)
