"""ケースごとにサービスをリセットし、adk evalの実行結果を集計する。"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from importlib.metadata import version
from dotenv import load_dotenv
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "evals/guest_ui_agent/.adk/eval_history"


def wait_ready(process, url):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("評価サービスが起動に失敗しました")
        try:
            if httpx.get(url, timeout=1).is_success:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise TimeoutError("評価サービスの起動を確認できません")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=[c["eval_id"] for c in json.loads((ROOT / "evals/restaurant.evalset.json").read_text())["eval_cases"]])
    parser.add_argument("--output", type=Path, default=ROOT / ".adk/restaurant-eval" / datetime.now().strftime("%Y%m%d-%H%M%S"))
    args = parser.parse_args()
    # 既存デモを停止・再利用せず、評価専用ポートだけを所有する。
    for port in (8800, 8803):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))
    args.output.mkdir(parents=True, exist_ok=False)
    load_dotenv(ROOT / ".env")
    env = dict(os.environ, PYTHONPATH=str(ROOT), RESTAURANT_AGENT_BASE_URL="http://127.0.0.1:8803",
               EVAL_GUEST_UI_URL="http://127.0.0.1:8800")
    cases = [c["eval_id"] for c in json.loads((ROOT / "evals/restaurant.evalset.json").read_text())["eval_cases"]]
    if args.case:
        cases = [args.case]
    metadata = {"model_front_desk": env.get("FRONT_DESK_MODEL", "ollama_chat/qwen3.5:latest"),
                "model_restaurant": env.get("OLLAMA_MODEL", "ollama_chat/qwen3.5:latest"),
                "settings": "temperature=0.1, num_ctx=8192, think=false; max_output_tokens=768/1200",
                "google-adk": version("google-adk"), "litellm": version("litellm"), "runs_per_case": 1}
    (args.output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    summary = []
    for case in cases:
        processes = []
        files = []
        try:
            env["EVAL_BASE_DATE"] = datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
            for name, module, port, health in (
                ("restaurant", "scripts.eval_restaurant_service:a2a_app", 8803, "/.well-known/agent-card.json"),
                ("guest-ui", "hotel_ui.app:app", 8800, "/health"),
            ):
                log = (args.output / f"{case}-{name}.log").open("w")
                files.append(log)
                process = subprocess.Popen([sys.executable, "-m", "uvicorn", module, "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
                processes.append(process)
                wait_ready(process, f"http://127.0.0.1:{port}{health}")
            before = set(HISTORY.glob("*.evalset_result.json"))
            command = [str(Path(sys.executable).parent / "adk"), "eval", "evals/guest_ui_agent",
                       f"evals/restaurant.evalset.json:{case}", "--config_file_path=evals/eval_config.json", "--print_detailed_results"]
            print(f"評価開始: {case}（再試行なし）", flush=True)
            with (args.output / f"{case}-adk.log").open("w") as log:
                evaluation = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
                processes.append(evaluation)
                returncode = evaluation.wait(timeout=1800)
            reports = set(HISTORY.glob("*.evalset_result.json")) - before
            results = []
            for report in reports:
                data = json.loads(report.read_text())
                (args.output / f"{case}-{report.name}").write_text(report.read_text())
                results.extend(data["eval_case_results"])
            same_day = datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat() == env["EVAL_BASE_DATE"]
            passed = same_day and returncode == 0 and len(results) == 1 and results[0]["eval_id"] == case and results[0]["final_eval_status"] == 1
            # ADK CLIは評価失敗でも終了コード0になるため、JSONの合否を必ず確認する。
            summary.append({"case": case, "passed": passed, "returncode": returncode, "baseline": env["EVAL_BASE_DATE"], "same_day": same_day})
            print(f"評価結果: {case}: {'PASS' if passed else 'FAIL'}", flush=True)
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
            for process in reversed(processes):
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for log in files:
                log.close()
            (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(f"結果保存先: {args.output}", flush=True)
    return 0 if len(summary) == len(cases) and all(item["passed"] for item in summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
