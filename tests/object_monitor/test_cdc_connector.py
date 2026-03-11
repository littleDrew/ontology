from datetime import datetime

from ontology.object_monitor.runtime import Neo4jKafkaCdcEventMapper, Neo4jKafkaSourceConfig


def test_neo4j_kafka_source_config_payload() -> None:
    config = Neo4jKafkaSourceConfig(
        connector_name="objm-neo4j-cdc",
        neo4j_uri="bolt://neo4j:7687",
        neo4j_user="neo4j",
        neo4j_password="secret",
        neo4j_database="neo4j",
        kafka_topic="object_change_raw",
        cdc_patterns=["(:Device)", "(:Device)-[:LOCATED_IN]->(:Plant)"],
        poll_interval="2s",
    )

    payload = config.to_connector_payload()
    cfg = payload["config"]
    assert payload["name"] == "objm-neo4j-cdc"
    assert cfg["neo4j.source-strategy"] == "CDC"
    assert cfg["neo4j.cdc.topic.object_change_raw.patterns"] == "(:Device),(:Device)-[:LOCATED_IN]->(:Plant)"
    assert cfg["neo4j.cdc.poll-interval"] == "2s"


def test_neo4j_kafka_cdc_event_mapper_from_connector_message() -> None:
    event = Neo4jKafkaCdcEventMapper.from_connector_message(
        {
            "id": "tx-100",
            "timestamp": datetime(2026, 2, 3, 10, 0, 0).isoformat(),
            "metadata": {"txId": "tx-100", "txSeq": 12},
            "event": {
                "elementId": "4:abc",
                "state": {
                    "before": {"device_id": "D1", "temperature": 70, "status": "IDLE"},
                    "after": {"device_id": "D1", "temperature": 85, "status": "RUNNING"},
                },
            },
        },
        tenant_id="t1",
        object_type="Device",
        object_id_field="device_id",
    )

    assert event.object_id == "D1"
    assert event.changed_fields == ["status", "temperature"]
    assert len(event.changed_properties) == 2
    assert event.source_version == 12
    assert event.object_version == 12


def test_neo4j_cdc_query_event_mapper() -> None:
    event = Neo4jKafkaCdcEventMapper.from_neo4j_cdc_query_event(
        {
            "id": "cdc-1",
            "metadata": {"txSeq": 33, "txCommitTime": "2026-02-03T10:00:00"},
            "event": {
                "state": {
                    "before": {"device_id": "D9", "temperature": 60},
                    "after": {"device_id": "D9", "temperature": 61},
                }
            },
        },
        tenant_id="t1",
        object_type="Device",
        object_id_field="device_id",
    )
    assert event.object_id == "D9"
    assert event.source_version == 33
    assert event.changed_fields == ["temperature"]
    assert event.changed_properties[0].old_value == 60
    assert event.changed_properties[0].new_value == 61


def test_neo4j_kafka_cdc_event_mapper_from_streams_shape_message() -> None:
    event = Neo4jKafkaCdcEventMapper.from_connector_message(
        {
            "meta": {
                "timestamp": 1773195063404,
                "username": "neo4j",
                "txId": 197,
                "txEventId": 0,
                "txEventsCount": 1,
                "operation": "updated",
                "source": {"hostname": "neo4j"},
            },
            "payload": {
                "id": "12",
                "before": {
                    "properties": {
                        "is_active": True,
                        "city": "北京",
                        "name": "张三",
                        "Job": "软件工程师",
                        "age": 30,
                    },
                    "labels": ["Person"],
                },
                "after": {
                    "properties": {
                        "is_active": True,
                        "city": "上海",
                        "name": "张三",
                        "Job": "软件工程师",
                        "age": 30,
                    },
                    "labels": ["Person"],
                },
                "type": "node",
            },
            "schema": {
                "properties": {
                    "is_active": "Boolean",
                    "city": "String",
                    "name": "String",
                    "Job": "String",
                    "age": "Long",
                },
                "Constraints": [],
            },
        },
        tenant_id="t1",
        object_type="Person",
        object_id_field="primary_key",
    )

    assert event.object_id == "12"
    assert event.changed_fields == ["city"]
    assert event.changed_properties[0].old_value == "北京"
    assert event.changed_properties[0].new_value == "上海"
    assert event.source_version == 197
    assert event.object_version == 197
    assert event.event_id == "197"
