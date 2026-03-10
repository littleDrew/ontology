from datetime import datetime, timedelta

from ontology.object_monitor.api import InMemoryMonitorReleaseService
from ontology.object_monitor.api.contracts import MonitorVersionStatus, ObjectChangeEvent
from ontology.object_monitor.runtime import ChangeNormalizer


def _sample_payload() -> dict:
    return {
        "monitor": {
            "id": "m_high_temp",
            "objectType": "Device",
            "scope": "plant_id in ['P1','P2']",
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


def test_w2_publish_switch_and_rollback_metadata() -> None:
    service = InMemoryMonitorReleaseService()
    base_time = datetime(2026, 1, 1, 0, 0, 0)

    v1 = service.create_definition(
        _sample_payload(),
        available_fields={"temperature", "status", "plant_id"},
        operator="alice",
        now=base_time,
    )
    payload2 = _sample_payload()
    payload2["condition"]["expr"] = "temperature >= 90 && status == 'RUNNING'"
    v2 = service.create_definition(
        payload2,
        available_fields={"temperature", "status", "plant_id"},
        operator="alice",
        now=base_time + timedelta(seconds=2),
    )

    published = service.publish("m_high_temp", v2.monitor_version, operator="release-bot", now=base_time + timedelta(seconds=3))
    assert published.status is MonitorVersionStatus.active
    assert service.get_active_artifact("m_high_temp").monitor_version == v2.monitor_version

    rollback = service.rollback("m_high_temp", v1.monitor_version, operator="release-bot", now=base_time + timedelta(seconds=4))
    assert rollback.status is MonitorVersionStatus.active
    assert rollback.rollback_from_version == v1.monitor_version
    assert service.get_active_artifact("m_high_temp").monitor_version == rollback.monitor_version


def test_w2_normalize_dedupe_outbox_cdc_double_emit() -> None:
    normalizer = ChangeNormalizer(dedupe_window_seconds=60)
    event_time = datetime(2026, 1, 1, 1, 0, 0)

    outbox = ObjectChangeEvent(
        event_id="e1",
        tenant_id="t1",
        object_type="Device",
        object_id="D1001",
        source_version=101,
        object_version=7,
        changed_fields=["status", "temperature"],
        event_time=event_time,
        trace_id="tr-1",
        change_source="outbox",
    )
    cdc_duplicate = ObjectChangeEvent(
        event_id="e2",
        tenant_id="t1",
        object_type="Device",
        object_id="D1001",
        source_version=101,
        object_version=7,
        changed_fields=["temperature", "status"],
        event_time=event_time + timedelta(seconds=1),
        trace_id="tr-2",
        change_source="neo4j_cdc",
    )

    first = normalizer.normalize(outbox)
    second = normalizer.normalize(cdc_duplicate)

    assert first.event is not None
    assert first.event.changed_fields == ["status", "temperature"]
    assert first.deduped is False
    assert second.event is None
    assert second.deduped is True


def test_w2_normalize_sends_version_regression_to_reconcile() -> None:
    normalizer = ChangeNormalizer(dedupe_window_seconds=60)
    event_time = datetime(2026, 1, 1, 2, 0, 0)

    normalizer.normalize(
        ObjectChangeEvent(
            event_id="newer",
            tenant_id="t1",
            object_type="Device",
            object_id="D9",
            source_version=200,
            object_version=9,
            changed_fields=["status"],
            event_time=event_time,
            trace_id="tr-new",
            change_source="outbox",
        )
    )

    older = normalizer.normalize(
        ObjectChangeEvent(
            event_id="older",
            tenant_id="t1",
            object_type="Device",
            object_id="D9",
            source_version=150,
            object_version=8,
            changed_fields=["status"],
            event_time=event_time + timedelta(seconds=1),
            trace_id="tr-old",
            change_source="neo4j_cdc",
        )
    )

    assert older.event is None
    assert older.reconcile_event is not None
    assert older.reconcile_event.expected_version == 9
    assert older.reconcile_event.actual_version == 8
