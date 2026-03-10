import os
import pytest
from neo4j import GraphDatabase

from ontology.object_monitor.runtime import Neo4jKafkaCdcEventMapper


def test_capture_real_neo4j_cdc_query_event() -> None:
    """Capture an actual CDC row from Neo4j and map it into ObjectChangeEvent."""
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")
    if not uri or not user or not password:
        pytest.skip("Neo4j credentials not configured")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session() as session:
        procedures = session.run("SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'db.cdc.' RETURN collect(name) AS names").single()
        names = procedures["names"] if procedures else []
        if "db.cdc.current" not in names or "db.cdc.query" not in names:
            pytest.skip("Neo4j CDC procedures unavailable (requires CDC-enabled Neo4j)")

        session.run("MATCH (n:Device) DETACH DELETE n")
        session.run("CREATE CONSTRAINT device_id_unique IF NOT EXISTS FOR (d:Device) REQUIRE d.device_id IS UNIQUE")

        cursor_row = session.run("CALL db.cdc.current() YIELD id RETURN id").single()
        cursor = cursor_row["id"]

        session.run(
            "MERGE (d:Device {device_id: $id}) "
            "SET d.temperature = $temp_old, d.status = $status_old",
            id="D-CDC-1",
            temp_old=70,
            status_old="IDLE",
        ).consume()
        session.run(
            "MATCH (d:Device {device_id: $id}) "
            "SET d.temperature = $temp_new, d.status = $status_new",
            id="D-CDC-1",
            temp_new=83,
            status_new="RUNNING",
        ).consume()

        rows = session.run("CALL db.cdc.query($cursor) YIELD id, txCommitTime, metadata, event RETURN id, txCommitTime, metadata, event", cursor=cursor).data()
        if not rows:
            pytest.skip("No CDC rows returned from Neo4j")

        mapped = [
            Neo4jKafkaCdcEventMapper.from_neo4j_cdc_query_event(
                {
                    "id": row["id"],
                    "txCommitTime": row["txCommitTime"],
                    "metadata": row["metadata"],
                    "event": row["event"],
                },
                tenant_id="t1",
                object_type="Device",
                object_id_field="device_id",
            )
            for row in rows
            if isinstance(row.get("event"), dict)
        ]

        updates = [evt for evt in mapped if "temperature" in evt.changed_fields or "status" in evt.changed_fields]
        assert updates, "expected at least one update CDC event"
        latest = updates[-1]
        assert latest.object_id == "D-CDC-1"
        assert any(item.field == "temperature" and item.new_value == 83 for item in latest.changed_properties)
        assert any(item.field == "status" and item.new_value == "RUNNING" for item in latest.changed_properties)
        assert latest.event_time is not None
