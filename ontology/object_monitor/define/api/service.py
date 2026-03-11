from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List
from uuid import uuid4

from ontology.object_monitor.define.api.contracts import (
    MonitorArtifact,
    MonitorDefinition,
    MonitorVersionRecord,
    MonitorVersionStatus,
)
from ontology.object_monitor.define.compiler.dsl import ValidationContext, parse_monitor_definition, validate_monitor_definition
from ontology.object_monitor.define.compiler.service import build_monitor_artifact


@dataclass
class _MonitorVersionBundle:
    """In-memory aggregate of definition, artifact and release metadata."""
    definition: MonitorDefinition
    artifact: MonitorArtifact
    record: MonitorVersionRecord


class InMemoryMonitorReleaseService:
    """W2 MVP publish chain with version switch and rollback metadata."""

    def __init__(self) -> None:
        self._by_monitor: Dict[str, Dict[int, _MonitorVersionBundle]] = {}

    def create_definition(
        self,
        payload: Dict[str, Any],
        *,
        available_fields: Iterable[str],
        operator: str,
        limits: Dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> MonitorVersionRecord:
        """Validate a monitor payload and store a new draft version."""
        parsed = parse_monitor_definition(payload)
        validate_monitor_definition(parsed, ValidationContext(available_fields=available_fields))
        now = now or datetime.utcnow()

        versions = self._by_monitor.setdefault(parsed.general.name, {})
        next_version = (max(versions.keys()) + 1) if versions else 1
        artifact = build_monitor_artifact(parsed, monitor_version=next_version, limits=limits)
        record = MonitorVersionRecord(
            monitor_id=parsed.general.name,
            monitor_version=next_version,
            plan_hash=artifact.plan_hash,
            status=MonitorVersionStatus.draft,
            command_id=f"cmd-{uuid4()}",
            operator=operator,
            created_at=now,
        )
        versions[next_version] = _MonitorVersionBundle(definition=parsed, artifact=artifact, record=record)
        return record

    def publish(self, monitor_id: str, monitor_version: int, *, operator: str, now: datetime | None = None) -> MonitorVersionRecord:
        """Activate a target version and archive any previously active version."""
        now = now or datetime.utcnow()
        bundle = self._require_bundle(monitor_id, monitor_version)
        for version, stored in self._by_monitor[monitor_id].items():
            if stored.record.status is MonitorVersionStatus.active and version != monitor_version:
                stored.record = MonitorVersionRecord(
                    **{**stored.record.__dict__, "status": MonitorVersionStatus.archived}
                )

        bundle.record = MonitorVersionRecord(
            **{
                **bundle.record.__dict__,
                "status": MonitorVersionStatus.active,
                "operator": operator,
                "command_id": f"cmd-{uuid4()}",
                "published_at": now,
            }
        )
        return bundle.record

    def rollback(self, monitor_id: str, target_version: int, *, operator: str, now: datetime | None = None) -> MonitorVersionRecord:
        """Clone a historical version into a new active rollback version."""
        now = now or datetime.utcnow()
        target = self._require_bundle(monitor_id, target_version)
        versions = self._by_monitor[monitor_id]
        new_version = max(versions.keys()) + 1

        cloned_artifact = MonitorArtifact(
            monitor_id=target.artifact.monitor_id,
            monitor_version=new_version,
            plan_hash=target.artifact.plan_hash,
            object_type=target.artifact.object_type,
            scope_predicate_ast=dict(target.artifact.scope_predicate_ast),
            field_projection=list(target.artifact.field_projection),
            rule_predicate_ast=dict(target.artifact.rule_predicate_ast),
            action_templates=[dict(item) for item in target.artifact.action_templates],
            runtime_policy=dict(target.artifact.runtime_policy),
        )
        record = MonitorVersionRecord(
            monitor_id=monitor_id,
            monitor_version=new_version,
            plan_hash=target.record.plan_hash,
            status=MonitorVersionStatus.active,
            command_id=f"cmd-{uuid4()}",
            operator=operator,
            created_at=now,
            published_at=now,
            rollback_from_version=target_version,
        )

        for version, stored in versions.items():
            if stored.record.status is MonitorVersionStatus.active:
                stored.record = MonitorVersionRecord(
                    **{**stored.record.__dict__, "status": MonitorVersionStatus.archived}
                )

        versions[new_version] = _MonitorVersionBundle(definition=target.definition, artifact=cloned_artifact, record=record)
        return record

    def get_active_artifact(self, monitor_id: str) -> MonitorArtifact:
        """Return the currently active artifact for a monitor id."""
        versions = self._by_monitor.get(monitor_id, {})
        for bundle in versions.values():
            if bundle.record.status is MonitorVersionStatus.active:
                return bundle.artifact
        raise KeyError(f"no active version for monitor: {monitor_id}")

    def list_active_artifacts(self) -> List[MonitorArtifact]:
        """Return active artifacts for all monitors."""
        artifacts: List[MonitorArtifact] = []
        for versions in self._by_monitor.values():
            for bundle in versions.values():
                if bundle.record.status is MonitorVersionStatus.active:
                    artifacts.append(bundle.artifact)
        return artifacts

    def _require_bundle(self, monitor_id: str, monitor_version: int) -> _MonitorVersionBundle:
        """Load a specific version bundle or raise a descriptive KeyError."""
        try:
            return self._by_monitor[monitor_id][monitor_version]
        except KeyError as exc:
            raise KeyError(f"monitor version not found: {monitor_id}#{monitor_version}") from exc
