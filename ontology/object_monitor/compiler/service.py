from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any, Dict

from ontology.object_monitor.api.contracts import MonitorArtifact, MonitorDefinition


def build_monitor_artifact(definition: MonitorDefinition, monitor_version: int, *, limits: Dict[str, Any] | None = None) -> MonitorArtifact:
    scope_predicate_ast = {
        "expr": definition.condition.object_set.scope,
        "phase": "L1",
    }
    rule_predicate_ast = {
        "expr": definition.condition.rule.expression,
        "phase": "L1",
    }
    action_templates = [
        {
            "name": action.name,
            "action_ref": action.action_ref,
            "parameters": action.parameters,
        }
        for action in definition.actions
    ]
    runtime_policy = {
        "idempotency_key_template": "${monitorId}:${objectId}:${sourceVersion}:${actionId}",
        "retry_policy": "none",
        "max_qps": (limits or {}).get("max_qps", 0),
    }

    normalized_payload = {
        "general": asdict(definition.general),
        "condition": {
            "object_set": asdict(definition.condition.object_set),
            "rule": asdict(definition.condition.rule),
        },
        "actions": [asdict(item) for item in definition.actions],
        "monitor_version": monitor_version,
        "limits": limits or {},
    }
    canonical = json.dumps(normalized_payload, sort_keys=True, separators=(",", ":"))
    plan_hash = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"

    return MonitorArtifact(
        monitor_id=definition.general.name,
        monitor_version=monitor_version,
        plan_hash=plan_hash,
        object_type=definition.general.object_type,
        scope_predicate_ast=scope_predicate_ast,
        field_projection=sorted(set(definition.condition.object_set.properties)),
        rule_predicate_ast=rule_predicate_ast,
        action_templates=action_templates,
        runtime_policy=runtime_policy,
    )
