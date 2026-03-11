from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence
from uuid import uuid4

from ontology.object_monitor.define.api.contracts import EvaluationRecord, EvaluationResult, MonitorArtifact, ObjectChangeEvent, ReconcileEvent
from ontology.object_monitor.runtime.context_builder import ContextStore
from ontology.object_monitor.runtime.storage.repository import InMemoryEvaluationLedger


class ReconcileQueue(Protocol):
    def push(self, event: ReconcileEvent) -> None: ...


@dataclass(frozen=True)
class EvaluatorConfig:
    reconcile_on_missing_context: bool = True


class L1Evaluator:
    """W4 stateless evaluator over context snapshot and compiled predicate AST."""

    def __init__(
        self,
        context_store: ContextStore,
        ledger: InMemoryEvaluationLedger,
        *,
        reconcile_queue: ReconcileQueue | None = None,
        config: EvaluatorConfig | None = None,
    ) -> None:
        self._context_store = context_store
        self._ledger = ledger
        self._reconcile_queue = reconcile_queue
        self._config = config or EvaluatorConfig()

    def evaluate_l1(self, event: ObjectChangeEvent, candidates: Sequence[MonitorArtifact]) -> list[EvaluationRecord]:
        try:
            snapshot = self._context_store.get(event.tenant_id, event.object_type, event.object_id)
        except Exception:
            self._push_reconcile(event, expected_version=event.object_version, actual_version=-1, reason="snapshot_fetch_failed")
            return []

        if snapshot is None:
            self._push_reconcile(event, expected_version=event.object_version, actual_version=-1, reason="snapshot_missing")
            return []

        if snapshot.object_version < event.object_version:
            self._push_reconcile(
                event,
                expected_version=event.object_version,
                actual_version=snapshot.object_version,
                reason="snapshot_version_behind",
            )
            return []

        records: list[EvaluationRecord] = []
        for artifact in candidates:
            started = time.perf_counter()
            condition = str(artifact.rule_predicate_ast.get("expr", "")).strip()
            matched = _eval_expr(condition, snapshot.payload)
            reason = f"expr={condition}"
            latency_ms = int((time.perf_counter() - started) * 1000)
            snapshot_hash = hashlib.sha256(str(sorted(snapshot.payload.items())).encode("utf-8")).hexdigest()

            record = EvaluationRecord(
                evaluation_id=str(uuid4()),
                tenant_id=event.tenant_id,
                monitor_id=artifact.monitor_id,
                monitor_version=artifact.monitor_version,
                object_id=event.object_id,
                source_version=event.source_version,
                result=EvaluationResult.hit if matched else EvaluationResult.miss,
                reason=reason,
                snapshot_hash=f"sha256:{snapshot_hash}",
                latency_ms=latency_ms,
                event_time=event.event_time,
            )
            if self._ledger.write_idempotent(record):
                records.append(record)
        return records

    def _push_reconcile(self, event: ObjectChangeEvent, *, expected_version: int, actual_version: int, reason: str) -> None:
        if self._reconcile_queue is None:
            return
        self._reconcile_queue.push(
            ReconcileEvent(
                tenant_id=event.tenant_id,
                object_type=event.object_type,
                object_id=event.object_id,
                expected_version=expected_version,
                actual_version=actual_version,
                reason=reason,
                trace_id=event.trace_id,
            )
        )

    def evaluate_l2(self, event: ObjectChangeEvent, candidates: Sequence[MonitorArtifact], window_spec: str) -> list[EvaluationRecord]:
        raise NotImplementedError("L2 evaluator is reserved for phase-2")


_CLAUSE_RE = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*$")
_STARTS_WITH_RE = re.compile(r"^\s*startsWith\(([a-zA-Z_][a-zA-Z0-9_]*),\s*'([^']*)'\)\s*$")
_IN_RE = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+in\s+\[(.*)\]\s*$")


def _eval_expr(expr: str, payload: Mapping[str, Any]) -> bool:
    if not expr:
        return False
    or_terms = [part.strip() for part in expr.split("||") if part.strip()]
    if not or_terms:
        return False
    for or_term in or_terms:
        and_terms = [part.strip() for part in or_term.split("&&") if part.strip()]
        if and_terms and all(_eval_clause(term, payload) for term in and_terms):
            return True
    return False


def _eval_clause(clause: str, payload: Mapping[str, Any]) -> bool:
    starts_match = _STARTS_WITH_RE.match(clause)
    if starts_match:
        field = starts_match.group(1)
        prefix = starts_match.group(2)
        value = payload.get(field)
        return isinstance(value, str) and value.startswith(prefix)

    in_match = _IN_RE.match(clause)
    if in_match:
        field = in_match.group(1)
        options = [item.strip() for item in in_match.group(2).split(",") if item.strip()]
        parsed = [_parse_literal(item) for item in options]
        return payload.get(field) in parsed

    match = _CLAUSE_RE.match(clause)
    if not match:
        return False
    field, op, raw_value = match.groups()
    left = payload.get(field)
    right = _parse_literal(raw_value)

    if op == "==":
        return left == right
    if op == "!=":
        return left != right

    try:
        left_num = float(left)
        right_num = float(right)
    except (TypeError, ValueError):
        return False

    if op == ">=":
        return left_num >= right_num
    if op == "<=":
        return left_num <= right_num
    if op == ">":
        return left_num > right_num
    if op == "<":
        return left_num < right_num
    return False


def _parse_literal(raw: str) -> Any:
    value = raw.strip()
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value
