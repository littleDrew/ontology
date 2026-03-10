from datetime import datetime, timedelta

from ontology.object_monitor.api.contracts import EvaluationRecord, EvaluationResult
from ontology.object_monitor.storage import (
    ActivityQuery,
    EvaluationQuery,
    SqlAlchemyActivityLedger,
    SqlAlchemyEvaluationLedger,
    SqlAlchemyMonitorReleaseService,
)
from ontology.object_monitor.storage.models import ActionDeliveryLogRow, MonitorActivityRow


def _payload() -> dict:
    return {
        "monitor": {
            "id": "m_sql",
            "objectType": "Device",
            "scope": "plant_id in ['P1']",
        },
        "input": {"fields": ["temperature", "status", "plant_id"]},
        "condition": {"expr": "temperature >= 80 && status == 'RUNNING'"},
        "effect": {
            "action": {
                "endpoint": "action://ticket/create",
                "idempotencyKey": "${monitorId}:${objectId}:${sourceVersion}",
            }
        },
    }


def test_sqlalchemy_release_service_publish_and_rollback() -> None:
    svc = SqlAlchemyMonitorReleaseService("sqlite:///:memory:")
    base = datetime(2026, 2, 1, 1, 0, 0)
    v1 = svc.create_definition(_payload(), available_fields={"temperature", "status", "plant_id"}, operator="alice", now=base)
    v2p = _payload()
    v2p["condition"]["expr"] = "temperature >= 90 && status == 'RUNNING'"
    v2 = svc.create_definition(v2p, available_fields={"temperature", "status", "plant_id"}, operator="alice", now=base + timedelta(seconds=1))

    published = svc.publish("m_sql", v2.monitor_version, operator="release", now=base + timedelta(seconds=2))
    assert published.monitor_version == v2.monitor_version
    assert svc.get_active_artifact("m_sql").monitor_version == v2.monitor_version

    rollback = svc.rollback("m_sql", v1.monitor_version, operator="release", now=base + timedelta(seconds=3))
    assert rollback.rollback_from_version == v1.monitor_version
    assert svc.get_active_artifact("m_sql").monitor_version == rollback.monitor_version


def test_sqlalchemy_ledgers_write_and_query() -> None:
    eval_ledger = SqlAlchemyEvaluationLedger("sqlite:///:memory:")
    act_ledger = SqlAlchemyActivityLedger("sqlite:///:memory:")

    record = EvaluationRecord(
        evaluation_id="ev1",
        tenant_id="t1",
        monitor_id="m1",
        monitor_version=1,
        object_id="D1",
        source_version=10,
        result=EvaluationResult.hit,
        reason="ok",
        snapshot_hash="sha256:x",
        latency_ms=3,
        event_time=datetime(2026, 2, 1, 9, 0, 0),
    )
    assert eval_ledger.write_idempotent(record) is True
    assert eval_ledger.write_idempotent(record) is False
    assert len(eval_ledger.query(EvaluationQuery(tenant_id="t1", monitor_id="m1"))) == 1

    activity = MonitorActivityRow(
        activity_id="a1",
        tenant_id="t1",
        monitor_id="m1",
        monitor_version=1,
        object_id="D1",
        source_version=10,
        status="queued",
        action_execution_id=None,
        event_time=datetime(2026, 2, 1, 9, 1, 0),
        updated_at=datetime(2026, 2, 1, 9, 1, 1),
    )
    act_ledger.upsert_activity(activity)
    act_ledger.append_delivery_log(
        ActionDeliveryLogRow(
            activity_id="a1",
            delivery_attempt=1,
            status="succeeded",
            error_code=None,
            error_message=None,
            created_at=datetime(2026, 2, 1, 9, 1, 2),
        )
    )
    assert len(act_ledger.query(ActivityQuery(tenant_id="t1", status="queued"))) == 1
    assert len(act_ledger.get_delivery_logs("a1")) == 1
