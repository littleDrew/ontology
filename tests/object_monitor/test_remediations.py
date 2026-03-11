import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from ontology.object_monitor.api.contracts import EvaluationRecord, EvaluationResult, ObjectChangeEvent
from ontology.object_monitor.compiler import build_monitor_artifact, parse_monitor_definition
from ontology.object_monitor.runtime import ContextBuilder, L1Evaluator, OntologyActionApiAdapter, ThinActionExecutor
from ontology.object_monitor.runtime.reconcile import InMemoryReconcileQueue
from ontology.object_monitor.storage import EvaluationQuery
from ontology.object_monitor.storage.sqlite_repository import SqliteEvaluationLedger


def _artifact(expr: str):
    payload = {
        "general": {"name": "m1", "description": "", "objectType": "Device", "enabled": True},
        "condition": {"objectSet": {"type": "Device", "properties": ["temperature", "status"]}, "rule": {"expression": expr}},
        "actions": [{"name": "apply", "actionRef": "action://demo/apply", "parameters": {}}],
    }
    return build_monitor_artifact(parse_monitor_definition(payload), monitor_version=1)


def test_p0_evaluator_routes_stale_snapshot_to_reconcile() -> None:
    builder = ContextBuilder()
    stale_event = ObjectChangeEvent(
        event_id="e1",
        tenant_id="t1",
        object_type="Device",
        object_id="D1",
        source_version=10,
        object_version=10,
        changed_fields=["temperature"],
        event_time=datetime(2026, 1, 8, 10, 0, 0),
        trace_id="tr-1",
    )
    builder.build(ObjectChangeEvent(**{**stale_event.__dict__, "object_version": 9}), object_payload={"temperature": 90, "status": "RUNNING"})

    queue = InMemoryReconcileQueue()
    evaluator = L1Evaluator(builder.store, SqliteEvaluationLedger(":memory:"), reconcile_queue=queue)
    records = evaluator.evaluate_l1(stale_event, [_artifact("temperature >= 80")])

    assert records == []
    events = queue.drain()
    assert len(events) == 1
    assert events[0].reason == "snapshot_version_behind"
    assert events[0].expected_version == 10
    assert events[0].actual_version == 9


def test_p0_action_api_adapter_integrates_with_thin_executor() -> None:
    captured = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            if not self.path.startswith("/api/v1/actions/a1/apply"):
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            captured.update(json.loads(body))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "execution_id": "exec-123",
                        "status": "succeeded",
                        "submitter": captured["submitter"],
                        "submitted_at": datetime.now(UTC).isoformat(),
                        "input_payload": captured["input_payload"],
                    }
                ).encode("utf-8")
            )

        def log_message(self, format, *args):  # noqa: A003
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        adapter = OntologyActionApiAdapter(base_url=f"http://127.0.0.1:{server.server_port}")
        executor = ThinActionExecutor(adapter)
        evaluation = EvaluationRecord(
            evaluation_id="ev1",
            tenant_id="t1",
            monitor_id="m1",
            monitor_version=1,
            object_id="D1",
            source_version=10,
            result=EvaluationResult.hit,
            reason="matched",
            snapshot_hash="sha256:x",
            latency_ms=1,
            event_time=datetime(2026, 1, 8, 11, 0, 0),
        )

        result = executor.execute(
            evaluation,
            action_id="a1",
            endpoint="action://demo/apply",
            payload={"ticket": "T-1"},
            idempotency_template="${monitorId}:${objectId}:${sourceVersion}:${actionId}",
        )
        assert result.success is True
        assert result.execution_id == "exec-123"
        assert captured["submitter"] == "monitor:a1"
        assert captured["client_request_id"] == "m1:D1:10:a1"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_p0_sqlite_evaluation_ledger_persist_and_query() -> None:
    eval_ledger = SqliteEvaluationLedger(":memory:")

    record = EvaluationRecord(
        evaluation_id="ev1",
        tenant_id="t1",
        monitor_id="m1",
        monitor_version=1,
        object_id="D1",
        source_version=1,
        result=EvaluationResult.hit,
        reason="ok",
        snapshot_hash="sha256:h",
        latency_ms=12,
        event_time=datetime(2026, 1, 8, 12, 0, 0),
    )
    assert eval_ledger.write_idempotent(record) is True
    assert eval_ledger.write_idempotent(record) is False
    rows = eval_ledger.query(EvaluationQuery(tenant_id="t1", monitor_id="m1"))
    assert len(rows) == 1
