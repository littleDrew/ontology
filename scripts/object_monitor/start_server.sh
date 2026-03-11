#!/usr/bin/env bash
set -euo pipefail

python -m ontology.servers.main_server --port 8765 &
MAIN_PID=$!
python -m ontology.servers.object_monitor_server --port 8771 --action-base-url http://127.0.0.1:8765 &
MONITOR_PID=$!
python -m ontology.servers.change_capture_server --port 8770 --data-plane-base-url http://127.0.0.1:8771 &
CAPTURE_PID=$!

cleanup() {
  kill "$CAPTURE_PID" "$MONITOR_PID" "$MAIN_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait
