"""UIやHTTPサーバーを起動せず、Restaurant単体をケースごとに評価する。"""
import argparse
from datetime import datetime
from importlib.metadata import version
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / 'evals/restaurant_agent/.adk/eval_history'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split', choices=['development', 'holdout'], default='development')
    parser.add_argument('--case')
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--output', type=Path, default=ROOT / '.adk/restaurant-agent-eval' / datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    args = parser.parse_args()
    if args.runs < 1:
        parser.error('--runsは1以上です')
    dataset = f'evals/restaurant_{args.split}.evalset.json'
    cases = [c['eval_id'] for c in json.loads((ROOT / dataset).read_text())['eval_cases']]
    if args.case:
        if args.case not in cases:
            parser.error('指定ケースはこのデータセットにありません')
        cases = [args.case]
    args.output.mkdir(parents=True, exist_ok=False)
    load_dotenv(ROOT / '.env')
    # 製品のRunConfig(max_llm_calls=8)と同じ上限をCLIにも適用する。
    env = dict(os.environ, PYTHONPATH=str(ROOT), ADK_MAX_LLM_CALLS='8')
    metadata = {'split': args.split, 'runs': args.runs, 'model': env.get('OLLAMA_MODEL', 'ollama_chat/qwen3.5:latest'),
                'google-adk': version('google-adk'), 'litellm': version('litellm'),
                'fixed_time': '2026-10-08T09:00:00+09:00', 'judge': None,
                'settings': 'temperature=0, num_ctx=8192, think=false, max_output_tokens=1200',
                'max_llm_calls': 8}
    sources = {Path(path) for path in [dataset, 'evals/eval_config.json', 'evals/metrics.py',
                                     'evals/__init__.py', 'scripts/eval_restaurant.py', 'pyproject.toml', 'uv.lock']}
    for directory in ('restaurant', 'agents/restaurant_agent', 'evals/restaurant_agent'):
        sources.update(path.relative_to(ROOT) for path in (ROOT / directory).rglob('*.py') if '.adk' not in path.parts)
    metadata['source_hashes'] = {str(path): hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in sorted(sources)}
    (args.output / 'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    summary = [{'case': case, 'run': run, 'status': 'NOT_RUN'} for case in cases for run in range(1, args.runs + 1)]
    summary_path = args.output / 'summary.json'
    try:
        for row in summary:
            case, run = row['case'], row['run']
            before = set(HISTORY.glob('*.evalset_result.json'))
            command = [str(Path(sys.executable).parent / 'adk'), 'eval', 'evals/restaurant_agent',
                       f'{dataset}:{case}', '--config_file_path=evals/eval_config.json', '--print_detailed_results']
            row['command'] = command
            print(f'評価開始: {case} ({run}/{args.runs})', flush=True)
            # 毎回別プロセスでAgent・会話・Repository・提案を初期化する。
            with (args.output / f'{case}-{run}-adk.log').open('w') as log:
                process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    row['returncode'] = process.wait(timeout=1800)
                except KeyboardInterrupt:
                    row['returncode'] = None
                    row['status'] = 'EXECUTION_ERROR'
                    row['error'] = '評価実行を中断したため、この試行は未検収'
                    raise
                except subprocess.TimeoutExpired:
                    row['returncode'] = None
                    row['error'] = '評価実行が1800秒でタイムアウト'
                    row['status'] = 'EXECUTION_ERROR'
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
            reports = set(HISTORY.glob('*.evalset_result.json')) - before
            results = []
            for report in reports:
                data = json.loads(report.read_text())
                (args.output / f'{case}-{run}-{report.name}').write_text(report.read_text())
                results.extend(data['eval_case_results'])
            if row['returncode'] != 0 or len(results) != 1 or results[0]['eval_id'] != case:
                row['status'] = 'EXECUTION_ERROR'
            else:
                metrics = {m['metric_name']: m['eval_status'] for m in results[0]['overall_eval_metric_results']}
                row['metrics'] = metrics
                gates = [metrics.get(name) for name in ('response_contract', 'tool_contract', 'outcome_contract')]
                if any(status not in (1, 2) for status in gates):
                    row['status'] = 'EXECUTION_ERROR'
                else:
                    row['status'] = 'PASS' if results[0]['final_eval_status'] == 1 and all(status == 1 for status in gates) else 'FAIL'
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
            print(f"評価結果: {case} ({run}/{args.runs}): {row['status']}", flush=True)
            if row['status'] == 'EXECUTION_ERROR':
                # 接続失敗等はモデル品質の不合格と区別し、残りを未実行として残す。
                break
    finally:
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    complete = all(row['status'] == 'PASS' for row in summary)
    print(f'結果保存先: {args.output}', flush=True)
    return 0 if complete else 1


if __name__ == '__main__':
    raise SystemExit(main())
