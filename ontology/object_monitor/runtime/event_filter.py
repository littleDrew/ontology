from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Set

from ontology.object_monitor.define.api.contracts import MonitorArtifact, ObjectChangeEvent

_SCOPE_IN_PATTERN = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+in\s+\[(.*)\]\s*$")
_SCOPE_EQ_PATTERN = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*==\s*'([^']*)'\s*$")


@dataclass(frozen=True)
class MonitorRuntimeSpec:
    artifact: MonitorArtifact
    object_type: str
    watched_fields: Set[str]


class EventFilter:
    """W3 two-stage filter: objectType+changed_fields then scope predicate."""

    def __init__(self) -> None:
        self._specs_by_object_type: Dict[str, List[MonitorRuntimeSpec]] = {}

    def load_specs(self, specs: Iterable[MonitorRuntimeSpec]) -> None:
        self._specs_by_object_type.clear()
        for spec in specs:
            self._specs_by_object_type.setdefault(spec.object_type, []).append(spec)

    def filter_candidates(self, event: ObjectChangeEvent, context_payload: Mapping[str, object]) -> List[MonitorArtifact]:
        candidates: List[MonitorArtifact] = []
        changed = set(event.changed_fields)
        specs = self._specs_by_object_type.get(event.object_type, [])
        for spec in specs:
            if spec.watched_fields and changed.isdisjoint(spec.watched_fields):
                continue
            scope_expr = str(spec.artifact.scope_predicate_ast.get("expr", "")).strip()
            if not _scope_matches(scope_expr, context_payload):
                continue
            candidates.append(spec.artifact)
        return candidates


def _scope_matches(scope_expr: str, context_payload: Mapping[str, object]) -> bool:
    if not scope_expr:
        return True

    in_match = _SCOPE_IN_PATTERN.match(scope_expr)
    if in_match:
        field = in_match.group(1)
        options = [token.strip().strip("'") for token in in_match.group(2).split(",") if token.strip()]
        return str(context_payload.get(field)) in options

    eq_match = _SCOPE_EQ_PATTERN.match(scope_expr)
    if eq_match:
        field = eq_match.group(1)
        expected = eq_match.group(2)
        return str(context_payload.get(field)) == expected

    return False
