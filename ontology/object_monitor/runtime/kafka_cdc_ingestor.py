from __future__ import annotations

import json
from dataclasses import dataclass

from kafka import KafkaConsumer

from ontology.object_monitor.api.contracts import ObjectChangeEvent
from ontology.object_monitor.runtime.cdc_connector import Neo4jKafkaCdcEventMapper
from ontology.object_monitor.runtime.change_pipeline import DualChannelIngestionPipeline


@dataclass
class KafkaCdcIngestor:
    """Consume Neo4j CDC messages from Kafka and feed DualChannelIngestionPipeline."""

    bootstrap_servers: str
    topic: str
    group_id: str
    tenant_id: str
    object_type: str
    object_id_field: str

    def poll_once(self, pipeline: DualChannelIngestionPipeline, timeout_ms: int = 5000) -> list[ObjectChangeEvent]:
        consumer = KafkaConsumer(
            self.topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        )
        try:
            batches = consumer.poll(timeout_ms=timeout_ms)
            cdc_events: list[ObjectChangeEvent] = []
            for records in batches.values():
                for record in records:
                    mapped = Neo4jKafkaCdcEventMapper.from_connector_message(
                        record.value,
                        tenant_id=self.tenant_id,
                        object_type=self.object_type,
                        object_id_field=self.object_id_field,
                    )
                    cdc_events.append(mapped)
            result = pipeline.ingest([], cdc_events)
            consumer.commit()
            return result.normalized_events
        finally:
            consumer.close()
