#!/usr/bin/env bash
set -euo pipefail

python -m scripts.object_monitor.main_server --port 8765 &
MAIN_PID=$!
python -m scripts.object_monitor.object_monitor_server --port 8771 --action-base-url http://127.0.0.1:8765 &
MONITOR_PID=$!

cleanup() {
  kill "$MONITOR_PID" "$MAIN_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait
