from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ontology.object_monitor.define.api.contracts import ObjectChangeEvent
from ontology.object_monitor.runtime.capture.normalizer import ChangeNormalizer
from ontology.object_monitor.runtime.capture.pipeline import SingleChannelIngestionPipeline
from ontology.object_monitor.runtime.capture.raw_consumer import RawConsumerRuntime, RawTopicMessage


def _canonical_payload() -> dict:
    return {
        "event_id": "evt-1",
        "tenant_id": "global",
        "object_type": "User",
        "object_id": "U100",
        "source_version": 10,
        "object_version": 10,
        "changed_fields": ["money"],
        "event_time": datetime(2026, 3, 1, 8, 0, 0, tzinfo=timezone.utc).isoformat(),
        "trace_id": "trace-1",
        "change_source": "outbox",
        "changed_properties": [{"field": "money", "old_value": 50, "new_value": 150}],
    }


def test_raw_consumer_runtime_normalizes_and_dispatches() -> None:
    seen: list[ObjectChangeEvent] = []
    runtime = RawConsumerRuntime(
        pipeline=SingleChannelIngestionPipeline(ChangeNormalizer(dedupe_window_seconds=60)),
        event_handler=lambda event: seen.append(event),
    )

    runtime.consume_message(RawTopicMessage(topic="object_change_raw", value=_canonical_payload()))
    runtime.consume_message(RawTopicMessage(topic="object_change_raw", value=_canonical_payload()))

    assert len(seen) == 1
    assert runtime.metrics.consumed == 2
    assert runtime.metrics.normalized == 1
    assert runtime.metrics.deduped == 1


def test_raw_consumer_runtime_retry_dlq_and_replay() -> None:
    attempts = {"count": 0}

    def flaky_handler(_: ObjectChangeEvent) -> None:
        attempts["count"] += 1
        if attempts["count"] <= 4:
            raise RuntimeError("handler_failed")

    runtime = RawConsumerRuntime(
        pipeline=SingleChannelIngestionPipeline(ChangeNormalizer(dedupe_window_seconds=60)),
        event_handler=flaky_handler,
    )

    now = datetime(2026, 3, 1, 8, 0, 0, tzinfo=timezone.utc)
    runtime.consume_message(RawTopicMessage(topic="object_change_raw", value=_canonical_payload(), offset=7), now=now)

    # 3 次重试后进入 dead letter
    runtime.process_retry_queue(now=now + timedelta(seconds=1))
    runtime.process_retry_queue(now=now + timedelta(seconds=6))
    runtime.process_retry_queue(now=now + timedelta(seconds=36))

    assert runtime.metrics.dead_lettered == 1
    dead_letters = runtime.dead_letters
    assert len(dead_letters) == 1

    # 修复后可 replay 成功
    attempts["count"] = 10
    runtime.replay_dead_letter(dead_letters[0].dead_letter_id, now=now + timedelta(seconds=40))
    runtime.process_retry_queue(now=now + timedelta(seconds=40))

    assert runtime.metrics.normalized == 1
    assert len(runtime.dead_letters) == 0


class _FakeKafkaConsumer:
    def __init__(self, records):
        self._records = records

    def poll(self, timeout_ms: int = 1000):
        _ = timeout_ms
        records = self._records
        self._records = {}
        return records

    def close(self) -> None:
        return None


def test_kafka_runner_consumes_messages_via_poll() -> None:
    from types import SimpleNamespace

    from ontology.object_monitor.runtime.capture.raw_consumer import KafkaConsumerConfig, KafkaRawConsumerRunner

    seen: list[ObjectChangeEvent] = []
    runtime = RawConsumerRuntime(
        pipeline=SingleChannelIngestionPipeline(ChangeNormalizer(dedupe_window_seconds=60)),
        event_handler=lambda event: seen.append(event),
    )
    topic_partition = "tp0"
    message = SimpleNamespace(key=None, value=_canonical_payload(), partition=0, offset=3)

    runner = KafkaRawConsumerRunner(
        runtime=runtime,
        config=KafkaConsumerConfig(bootstrap_servers="fake:9092"),
        consumer_factory=lambda cfg: _FakeKafkaConsumer({topic_partition: [message]}),
    )

    consumed = runner.run_once()
    assert consumed == 1
    assert runtime.metrics.consumed == 1
    assert len(seen) == 1
