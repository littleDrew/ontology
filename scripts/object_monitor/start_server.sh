#!/usr/bin/env bash
set -euo pipefail

python -m scripts.object_monitor.main_server --port 8765 &
MAIN_PID=$!

MONITOR_ARGS=(--port 8771 --action-base-url http://127.0.0.1:8765)
if [[ -n "${KAFKA_BOOTSTRAP_SERVERS:-}" ]]; then
  MONITOR_ARGS+=(--kafka-bootstrap-servers "$KAFKA_BOOTSTRAP_SERVERS")
  MONITOR_ARGS+=(--kafka-topic "${KAFKA_TOPIC:-object_change_raw}")
  MONITOR_ARGS+=(--kafka-group-id "${KAFKA_GROUP_ID:-object-monitor-runtime}")
fi

python -m scripts.object_monitor.object_monitor_server "${MONITOR_ARGS[@]}" &
MONITOR_PID=$!

cleanup() {
  kill "$MONITOR_PID" "$MAIN_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait
