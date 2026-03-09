from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ontology.object_monitor.api.contracts import ReconcileEvent


@dataclass
class InMemoryReconcileQueue:
    _events: List[ReconcileEvent]

    def __init__(self) -> None:
        self._events = []

    def push(self, event: ReconcileEvent) -> None:
        self._events.append(event)

    def drain(self) -> List[ReconcileEvent]:
        events = list(self._events)
        self._events.clear()
        return events

    def size(self) -> int:
        return len(self._events)
