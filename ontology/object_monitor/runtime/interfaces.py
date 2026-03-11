from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from ontology.object_monitor.define.api.contracts import EvaluationRecord, MonitorArtifact, ObjectChangeEvent


class Evaluator(Protocol):
    def evaluate_l1(self, event: ObjectChangeEvent, candidates: Sequence[MonitorArtifact]) -> Sequence[EvaluationRecord]: ...

    def evaluate_l2(self, event: ObjectChangeEvent, candidates: Sequence[MonitorArtifact], window_spec: str) -> Sequence[EvaluationRecord]: ...


class EffectExecutor(Protocol):
    def execute_action(self, evaluation: EvaluationRecord) -> None: ...

    def execute_notification(self, evaluation: EvaluationRecord) -> None: ...


class ReplayService(Protocol):
    def replay(self, monitor_id: str, time_range: str, monitor_version: int | None = None) -> int: ...


@dataclass(frozen=True)
class RuntimeCommand:
    command_id: str
    monitor_id: str
    monitor_version: int
    action: str
