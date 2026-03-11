from datetime import datetime

from ontology.object_monitor.runtime.storage.sqlalchemy_repository import SqlAlchemyEvaluationLedger
from ontology.object_monitor.define.storage.sqlalchemy_repository import SqlAlchemyMonitorReleaseService
from ontology.object_monitor.define.api.contracts import EvaluationRecord, EvaluationResult


def _sample_payload() -> dict:
    return {
        "general": {
            "name": "m_high_temp",
            "description": "",
            "objectType": "Device",
            "enabled": True,
        },
        "condition": {
            "objectSet": {
                "type": "Device",
                "scope": "plant_id in ['P1','P2']",
                "properties": ["temperature", "status", "plant_id"],
            },
            "rule": {"expression": "temperature >= 80 && status == 'RUNNING'"},
        },
        "actions": [{"name": "create_ticket", "actionRef": "action://ticket/create", "parameters": {}}],
    }


def test_sqlalchemy_release_service_roundtrip() -> None:
    svc = SqlAlchemyMonitorReleaseService("sqlite:///:memory:")
    v1 = svc.create_definition(_sample_payload(), available_fields={"temperature", "status", "plant_id"}, operator="alice")
    assert v1.monitor_version == 1

    pub = svc.publish("m_high_temp", 1, operator="bot")
    assert pub.status.value == "active"
    active = svc.get_active_artifact("m_high_temp")
    assert active.monitor_id == "m_high_temp"


def test_sqlalchemy_evaluation_ledger_idempotent_write() -> None:
    ledger = SqlAlchemyEvaluationLedger("sqlite:///:memory:")
    row = EvaluationRecord(
        evaluation_id="e1",
        tenant_id="t1",
        monitor_id="m1",
        monitor_version=1,
        object_id="o1",
        source_version=1,
        result=EvaluationResult.hit,
        reason="ok",
        snapshot_hash="sha256:x",
        latency_ms=1,
        event_time=datetime(2026, 1, 1, 0, 0, 0),
    )
    assert ledger.write_idempotent(row) is True
    assert ledger.write_idempotent(row) is False
