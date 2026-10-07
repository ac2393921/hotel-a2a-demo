#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GUEST_UI_PORT="${GUEST_UI_PORT:-8000}"
cd "$ROOT_DIR"

declare -a PIDS=()
declare -a SERVICES=()

start_service() {
  local service="$1"
  shift

  "$@" &
  local pid=$!
  PIDS+=("$pid")
  SERVICES+=("$service")
  printf '[起動中] %s (PID: %s)\n' "$service" "$pid"
}

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM

  printf '\n[停止中] 起動したサービスを停止します...\n'
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  for pid in "${PIDS[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
  printf '[停止完了] すべてのサービスを停止しました。\n'
  exit "$exit_code"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

start_service "Maintenance Agent" \
  uv run uvicorn agents.maintenance_agent.agent:a2a_app \
  --host 127.0.0.1 --port 8001
start_service "Housekeeping Agent" \
  uv run uvicorn agents.housekeeping_agent.agent:a2a_app \
  --host 127.0.0.1 --port 8002
start_service "Restaurant Agent" \
  uv run uvicorn agents.restaurant_agent.agent:a2a_app \
  --host 127.0.0.1 --port 8003
start_service "Front Desk A2Aサービス" \
  uv run uvicorn agents.front_desk_agent.agent:a2a_app \
  --host 127.0.0.1 --port 8004
start_service "Guest UI" \
  uv run uvicorn hotel_ui.app:app \
  --host 127.0.0.1 --port "$GUEST_UI_PORT"

for second in {1..10}; do
  sleep 1
  for index in "${!PIDS[@]}"; do
    if ! kill -0 "${PIDS[$index]}" 2>/dev/null; then
      set +e
      wait "${PIDS[$index]}"
      exit_code=$?
      set -e
      printf '[起動失敗] %s が終了しました (終了コード: %s)。\n' \
        "${SERVICES[$index]}" "$exit_code" >&2
      exit 1
    fi
  done
done

printf '\n[起動完了] Guest UI: http://127.0.0.1:%s\n' "$GUEST_UI_PORT"
printf '[終了方法] Ctrl+Cですべてのサービスを停止します。\n\n'

while true; do
  for index in "${!PIDS[@]}"; do
    if ! kill -0 "${PIDS[$index]}" 2>/dev/null; then
      set +e
      wait "${PIDS[$index]}"
      exit_code=$?
      set -e
      printf '[異常終了] %s が終了しました (終了コード: %s)。\n' \
        "${SERVICES[$index]}" "$exit_code" >&2
      exit 1
    fi
  done
  sleep 1
done
