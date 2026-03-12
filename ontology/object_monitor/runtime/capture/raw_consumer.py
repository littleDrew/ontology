from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import threading
import time
from typing import Any, Callable, Dict, Protocol

from ontology.object_monitor.define.api.contracts import ObjectChangeEvent, PropertyChange
from ontology.object_monitor.runtime.capture.pipeline import SingleChannelIngestionPipeline


@dataclass(frozen=True)
class RawTopicMessage:
    topic: str
    value: dict[str, Any]
    key: str | None = None
    partition: int = 0
    offset: int = 0


@dataclass
class RetryMessage:
    message: RawTopicMessage
    attempt: int
    next_attempt_at: datetime
    last_error: str
    normalized_events: list[ObjectChangeEvent] = field(default_factory=list)


@dataclass
class DeadLetterMessage:
    dead_letter_id: str
    message: RawTopicMessage
    attempts: int
    error: str
    failed_at: datetime
    normalized_events: list[ObjectChangeEvent] = field(default_factory=list)


@dataclass
class RawConsumerMetrics:
    consumed: int = 0
    normalized: int = 0
    deduped: int = 0
    reconciliations: int = 0
    retried: int = 0
    dead_lettered: int = 0


class RawEventParser:
    """Parse raw topic payload into ObjectChangeEvent.

    Supported payload shapes:
    1) canonical ObjectChangeEvent dict
    2) Neo4j Streams envelope {meta, payload}
    """

    def parse(self, payload: dict[str, Any], *, default_tenant_id: str = "global") -> ObjectChangeEvent:
        if "event_id" in payload and "object_type" in payload:
            return self._from_object_change(payload)
        if "meta" in payload and "payload" in payload:
            return self._from_streams(payload, default_tenant_id=default_tenant_id)
        raise ValueError("unsupported_raw_event_payload")

    def _from_object_change(self, payload: dict[str, Any]) -> ObjectChangeEvent:
        event_time_raw = payload.get("event_time")
        if isinstance(event_time_raw, datetime):
            event_time = event_time_raw
        else:
            event_time = datetime.fromisoformat(str(event_time_raw).replace("Z", "+00:00"))
        props = [
            PropertyChange(field=str(item["field"]), old_value=item.get("old_value"), new_value=item.get("new_value"))
            for item in payload.get("changed_properties", [])
        ]
        return ObjectChangeEvent(
            event_id=str(payload["event_id"]),
            tenant_id=str(payload.get("tenant_id", "global")),
            object_type=str(payload["object_type"]),
            object_id=str(payload["object_id"]),
            source_version=int(payload["source_version"]),
            object_version=int(payload["object_version"]),
            changed_fields=[str(item) for item in payload.get("changed_fields", [])],
            event_time=event_time,
            trace_id=str(payload.get("trace_id", payload["event_id"])),
            change_source=str(payload.get("change_source", "outbox")),
            changed_properties=props,
        )

    def _from_streams(self, envelope: dict[str, Any], *, default_tenant_id: str) -> ObjectChangeEvent:
        meta = envelope.get("meta", {})
        payload = envelope.get("payload", {})
        before = ((payload.get("before") or {}).get("properties")) or {}
        after = ((payload.get("after") or {}).get("properties")) or {}

        changed_properties: list[PropertyChange] = []
        changed_fields: list[str] = []
        for key in sorted(set(before.keys()) | set(after.keys())):
            old_value = before.get(key)
            new_value = after.get(key)
            if old_value != new_value:
                changed_fields.append(key)
                changed_properties.append(PropertyChange(field=key, old_value=old_value, new_value=new_value))

        timestamp_ms = int(meta.get("timestamp", 0))
        event_time = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        object_type, object_id = _resolve_streams_object_identity(payload)
        txid = str(meta.get("txId", "0"))
        return ObjectChangeEvent(
            event_id=txid,
            tenant_id=default_tenant_id,
            object_type=object_type,
            object_id=object_id,
            source_version=int(meta.get("txId", 0)),
            object_version=int(meta.get("txId", 0)),
            changed_fields=changed_fields,
            event_time=event_time,
            trace_id=txid,
            change_source="neo4j_streams",
            changed_properties=changed_properties,
        )


def _resolve_streams_object_identity(payload: dict[str, Any]) -> tuple[str, str]:
    entity_type = str(payload.get("type", "")).lower()
    if entity_type == "relationship":
        relation_label = payload.get("label") or "Relationship"
        relation_id = payload.get("id")
        if relation_id is None:
            start_id = (payload.get("start") or {}).get("id")
            end_id = (payload.get("end") or {}).get("id")
            relation_id = f"{start_id}->{relation_label}->{end_id}"
        return str(relation_label), str(relation_id)

    labels = ((payload.get("after") or {}).get("labels")) or ((payload.get("before") or {}).get("labels")) or ["Unknown"]
    return str(labels[0]), str(payload.get("id", ""))


class RawConsumerRuntime:
    """Consume object_change_raw messages in-process and dispatch normalized events."""

    RETRY_DELAYS = [timedelta(seconds=1), timedelta(seconds=5), timedelta(seconds=30)]

    def __init__(
        self,
        *,
        pipeline: SingleChannelIngestionPipeline,
        event_handler: Callable[[ObjectChangeEvent], None],
        parser: RawEventParser | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._event_handler = event_handler
        self._parser = parser or RawEventParser()
        self.metrics = RawConsumerMetrics()
        self._retry_queue: list[RetryMessage] = []
        self._dead_letters: dict[str, DeadLetterMessage] = {}

    @property
    def dead_letters(self) -> list[DeadLetterMessage]:
        return list(self._dead_letters.values())

    @property
    def retry_queue_size(self) -> int:
        return len(self._retry_queue)

    def consume_message(self, message: RawTopicMessage, *, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self.metrics.consumed += 1
        try:
            event = self._parser.parse(message.value)
            result = self._pipeline.ingest([event])
            self.metrics.deduped += result.deduped_count
            self.metrics.reconciliations += len(result.reconcile_events)
            for normalized in result.normalized_events:
                self._event_handler(normalized)
                self.metrics.normalized += 1
        except Exception as exc:  # noqa: BLE001
            self._schedule_retry(
                message,
                error=str(exc),
                now=now,
                normalized_events=result.normalized_events if "result" in locals() else None,
            )

    def process_retry_queue(self, *, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        pending = sorted(self._retry_queue, key=lambda row: row.next_attempt_at)
        self._retry_queue = []
        for row in pending:
            if row.next_attempt_at > now:
                self._retry_queue.append(row)
                continue
            self._retry_or_dlq(row, now=now)

    def replay_dead_letter(self, dead_letter_id: str, *, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        dead = self._dead_letters.pop(dead_letter_id)
        self._retry_queue.append(
            RetryMessage(
                message=dead.message,
                attempt=0,
                next_attempt_at=now,
                last_error=dead.error,
                normalized_events=list(dead.normalized_events),
            )
        )

    def export_dead_letter_json(self) -> str:
        rows: list[Dict[str, Any]] = []
        for row in self.dead_letters:
            rows.append(
                {
                    "dead_letter_id": row.dead_letter_id,
                    "topic": row.message.topic,
                    "partition": row.message.partition,
                    "offset": row.message.offset,
                    "attempts": row.attempts,
                    "error": row.error,
                    "failed_at": row.failed_at.isoformat(),
                    "value": row.message.value,
                }
            )
        return json.dumps(rows, ensure_ascii=False)

    def _retry_or_dlq(self, row: RetryMessage, *, now: datetime) -> None:
        try:
            if row.normalized_events:
                for normalized in row.normalized_events:
                    self._event_handler(normalized)
                    self.metrics.normalized += 1
                return
            event = self._parser.parse(row.message.value)
            result = self._pipeline.ingest([event])
            self.metrics.deduped += result.deduped_count
            self.metrics.reconciliations += len(result.reconcile_events)
            for normalized in result.normalized_events:
                self._event_handler(normalized)
                self.metrics.normalized += 1
        except Exception as exc:  # noqa: BLE001
            self._schedule_retry(
                row.message,
                error=str(exc),
                now=now,
                attempt=row.attempt,
                normalized_events=row.normalized_events or (result.normalized_events if "result" in locals() else None),
            )

    def _schedule_retry(
        self,
        message: RawTopicMessage,
        *,
        error: str,
        now: datetime,
        attempt: int = 0,
        normalized_events: list[ObjectChangeEvent] | None = None,
    ) -> None:
        next_attempt = attempt + 1
        if next_attempt > len(self.RETRY_DELAYS):
            dead_letter_id = f"{message.topic}:{message.partition}:{message.offset}"
            self._dead_letters[dead_letter_id] = DeadLetterMessage(
                dead_letter_id=dead_letter_id,
                message=message,
                attempts=next_attempt,
                error=error,
                failed_at=now,
                normalized_events=list(normalized_events or []),
            )
            self.metrics.dead_lettered += 1
            return
        self.metrics.retried += 1
        self._retry_queue.append(
            RetryMessage(
                message=message,
                attempt=next_attempt,
                next_attempt_at=now + self.RETRY_DELAYS[next_attempt - 1],
                last_error=error,
                normalized_events=list(normalized_events or []),
            )
        )


class KafkaConsumerAdapter(Protocol):
    def poll(self, timeout_ms: int = 1000) -> dict[Any, list[Any]]: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class KafkaConsumerConfig:
    bootstrap_servers: str
    topic: str = "object_change_raw"
    group_id: str = "object-monitor-runtime"
    auto_offset_reset: str = "latest"
    enable_auto_commit: bool = True
    poll_timeout_ms: int = 1000


class KafkaRawConsumerRunner:
    """Background kafka-python consumer that feeds RawConsumerRuntime."""

    def __init__(
        self,
        *,
        runtime: RawConsumerRuntime,
        config: KafkaConsumerConfig,
        consumer_factory: Callable[[KafkaConsumerConfig], KafkaConsumerAdapter] | None = None,
    ) -> None:
        self._runtime = runtime
        self._config = config
        self._consumer_factory = consumer_factory or _default_kafka_consumer_factory
        self._consumer: KafkaConsumerAdapter | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._consumer = self._consumer_factory(self._config)
        self._thread = threading.Thread(target=self._run_loop, name="object-monitor-kafka-consumer", daemon=True)
        self._thread.start()

    def stop(self, *, timeout_seconds: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_seconds)
        if self._consumer is not None:
            self._consumer.close()
        self._thread = None
        self._consumer = None

    def run_once(self) -> int:
        if self._consumer is None:
            self._consumer = self._consumer_factory(self._config)
        records = self._consumer.poll(timeout_ms=self._config.poll_timeout_ms)
        consumed = 0
        for topic_partition, messages in records.items():
            topic = getattr(topic_partition, "topic", self._config.topic)
            for msg in messages:
                payload = getattr(msg, "value", None)
                if not isinstance(payload, dict):
                    continue
                self._runtime.consume_message(
                    RawTopicMessage(
                        topic=topic,
                        value=payload,
                        key=str(getattr(msg, "key", "") or ""),
                        partition=int(getattr(msg, "partition", 0) or 0),
                        offset=int(getattr(msg, "offset", 0) or 0),
                    )
                )
                consumed += 1
        self._runtime.process_retry_queue()
        return consumed

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self.run_once()
            time.sleep(0.05)


def _default_kafka_consumer_factory(config: KafkaConsumerConfig) -> KafkaConsumerAdapter:
    from kafka import KafkaConsumer

    return KafkaConsumer(
        config.topic,
        bootstrap_servers=config.bootstrap_servers,
        group_id=config.group_id,
        auto_offset_reset=config.auto_offset_reset,
        enable_auto_commit=config.enable_auto_commit,
        value_deserializer=lambda payload: json.loads(payload.decode("utf-8")),
    )
