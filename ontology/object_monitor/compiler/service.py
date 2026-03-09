from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any, Dict

from ontology.object_monitor.api.contracts import MonitorArtifact, MonitorDefinition


def build_monitor_artifact(definition: MonitorDefinition, monitor_version: int, *, limits: Dict[str, Any] | None = None) -> MonitorArtifact:
    predicate_ast = {
        "scope": definition.monitor.scope,
        "condition": definition.condition.expr,
        "phase": "L1",
    }
    action_template = {
        "endpoint": definition.effect.action.endpoint,
        "idempotency_key": definition.effect.action.idempotency_key,
    }
    normalized_payload = {
        "monitor": asdict(definition.monitor),
        "input": asdict(definition.input),
        "condition": asdict(definition.condition),
        "effect": {
            "action": {
                "endpoint": definition.effect.action.endpoint,
                "idempotency_key": definition.effect.action.idempotency_key,
            }
        },
        "monitor_version": monitor_version,
        "limits": limits or {},
    }
    canonical = json.dumps(normalized_payload, sort_keys=True, separators=(",", ":"))
    plan_hash = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"

    return MonitorArtifact(
        monitor_id=definition.monitor.id,
        monitor_version=monitor_version,
        plan_hash=plan_hash,
        field_projection=sorted(set(definition.input.fields)),
        predicate_ast=predicate_ast,
        action_template=action_template,
        limits=limits or {},
    )
