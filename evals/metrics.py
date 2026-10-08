"""応答・tool引数・業務結果を別々に採点し、全ターンの合格を要求する。"""
import json
import re
from datetime import date

from google.adk.evaluation.eval_case import get_all_tool_calls, get_all_tool_responses
from google.adk.evaluation.evaluator import EvaluationResult, PerInvocationResult
from google.adk.evaluation.eval_metrics import EvalStatus


def _text(invocation):
    if invocation.final_response is None:
        return ""
    return "".join(part.text or "" for part in invocation.final_response.parts or [])


def _correct_weekdays(text):
    """応答に曜日を付けた場合は、その日付の実際の曜日と照合する。"""
    pattern = r"(\d{4})(?:年|[-/])(\d{1,2})(?:月|[-/])(\d{1,2})日?\s*(?:[（(]\s*([月火水木金土日])(?:曜日)?\s*[）)]|([月火水木金土日])曜(?:日)?)"
    for match in re.finditer(pattern, text):
        year, month, day, parenthesized, plain = match.groups()
        weekday = parenthesized or plain
        try:
            if "月火水木金土日"[date(int(year), int(month), int(day)).weekday()] != weekday:
                return False
        except ValueError:
            return False
    return True


def _matches_args(call, expected):
    # 省略された任意引数は製品toolの既定値と同じ意味になる。
    args = {"expand_time": False, "alternate_seat": "", **(call.args or {})}
    return all(args.get(key) == value for key, value in expected.items())


def _check(invocation, rules, dimension):
    calls = get_all_tool_calls(invocation.intermediate_data)
    responses = get_all_tool_responses(invocation.intermediate_data)
    if dimension == "response":
        text = _text(invocation)
        return bool(text) and _correct_weekdays(text) and all(re.search(p, text) for p in rules["required"]) and not any(
            re.search(p, text) for p in rules["forbidden"])
    if dimension == "tools":
        allowed = rules["allowed_tools"]
        if any(call.name not in allowed for call in calls):
            return False
        for call in calls:
            expected_args = [expected["args"] for expected in rules["tools"] if expected["name"] == call.name]
            if expected_args and not any(_matches_args(call, args) for args in expected_args):
                return False
        # 必須呼び出しの引数まで照合する。動的IDは期待値にしない。
        offset = 0
        for expected in rules["tools"]:
            for index in range(offset, len(calls)):
                call = calls[index]
                if call.name == expected["name"] and _matches_args(call, expected["args"]):
                    offset = index + 1
                    break
            else:
                return False
        return True
    if dimension == "outcome":
        if "approval_token" in invocation.model_dump_json():
            return False
        for expected in rules["outcomes"]:
            if not any(response.name == expected["name"] and all(
                (response.response or {}).get(key) == value for key, value in expected["fields"].items())
                       for response in responses):
                return False
        return True
    raise ValueError("未定義の評価軸です")


def evaluate_dimension(actual_invocations, expected_invocations, dimension):
    if not expected_invocations or len(actual_invocations) != len(expected_invocations):
        return EvaluationResult(overall_score=0, overall_eval_status=EvalStatus.FAILED)
    results = []
    for actual, expected in zip(actual_invocations, expected_invocations, strict=True):
        try:
            passed = _check(actual, json.loads(_text(expected)), dimension)
        except (ValueError, TypeError, KeyError, AttributeError):
            passed = False
        results.append(PerInvocationResult(actual_invocation=actual, expected_invocation=expected,
                                          score=float(passed), eval_status=EvalStatus.PASSED if passed else EvalStatus.FAILED))
    passed = all(result.eval_status == EvalStatus.PASSED for result in results)
    return EvaluationResult(overall_score=float(passed), overall_eval_status=EvalStatus.PASSED if passed else EvalStatus.FAILED,
                            per_invocation_results=results)


def response_contract(metric, actual_invocations, expected_invocations=None, conversation_scenario=None):
    return evaluate_dimension(actual_invocations, expected_invocations, "response")


def tool_contract(metric, actual_invocations, expected_invocations=None, conversation_scenario=None):
    return evaluate_dimension(actual_invocations, expected_invocations, "tools")


def outcome_contract(metric, actual_invocations, expected_invocations=None, conversation_scenario=None):
    return evaluate_dimension(actual_invocations, expected_invocations, "outcome")
