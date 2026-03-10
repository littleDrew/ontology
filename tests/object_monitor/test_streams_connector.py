from datetime import datetime

from ontology.object_monitor.runtime import Neo4jStreamsEventMapper


def test_streams_event_mapper_from_message() -> None:
    event = Neo4jStreamsEventMapper.from_streams_message(
        {
            "meta": {"txId": 1024, "txSeq": 1024, "timestamp": datetime(2026, 3, 1, 10, 30, 0).isoformat()},
            "payload": {
                "before": {"properties": {"primary_key": "U-1", "money": 50, "tag": "poor"}},
                "after": {"properties": {"primary_key": "U-1", "money": 150, "tag": "poor"}},
            },
        },
        tenant_id="t1",
        object_type="User",
        object_id_field="primary_key",
    )

    assert event.object_type == "User"
    assert event.object_id == "U-1"
    assert event.change_source == "neo4j_streams"
    assert event.changed_fields == ["money"]
    assert len(event.changed_properties) == 1
    assert event.changed_properties[0].old_value == 50
    assert event.changed_properties[0].new_value == 150
