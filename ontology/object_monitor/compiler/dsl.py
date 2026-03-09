from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping

from ontology.object_monitor.api.contracts import (
    ActionEffect,
    ConditionDefinition,
    EffectDefinition,
    InputBinding,
    MonitorDefinition,
    MonitorEnvelope,
)

_ALLOWED_FUNCTIONS = ("startsWith",)
_ALLOWED_OPERATORS = ("&&", "||", "==", "!=", ">=", "<=", ">", "<", " in ")
_FIELD_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_\.]*$")


class DSLValidationError(ValueError):
    """Raised when monitor DSL is invalid."""


@dataclass(frozen=True)
class ValidationContext:
    available_fields: Iterable[str]
    max_ast_nodes: int = 64


def parse_monitor_definition(payload: Mapping[str, Any]) -> MonitorDefinition:
    """Parse Phase-1 minimal monitor DSL from a dict payload."""
    try:
        monitor = payload["monitor"]
        input_section = payload["input"]
        condition = payload["condition"]
        effect = payload["effect"]
        action = effect["action"]
    except KeyError as exc:
        raise DSLValidationError(f"missing required section: {exc.args[0]}") from exc

    return MonitorDefinition(
        monitor=MonitorEnvelope(
            id=str(monitor["id"]),
            object_type=str(monitor["objectType"]),
            scope=str(monitor.get("scope", "")),
        ),
        input=InputBinding(fields=[str(field) for field in input_section["fields"]]),
        condition=ConditionDefinition(expr=str(condition["expr"])),
        effect=EffectDefinition(
            action=ActionEffect(
                endpoint=str(action["endpoint"]),
                idempotency_key=str(action["idempotencyKey"]),
            )
        ),
    )


def validate_monitor_definition(definition: MonitorDefinition, context: ValidationContext) -> None:
    available_fields = set(context.available_fields)
    if not definition.monitor.id:
        raise DSLValidationError("monitor.id cannot be empty")
    if not definition.monitor.object_type:
        raise DSLValidationError("monitor.objectType cannot be empty")

    _validate_fields(definition.input.fields, available_fields)
    _validate_expression(definition.condition.expr, context.max_ast_nodes)
    _validate_expression(definition.monitor.scope, context.max_ast_nodes, allow_empty=True)
    _validate_action(definition.effect.action)


def _validate_fields(fields: Iterable[str], available_fields: set[str]) -> None:
    materialized_fields = list(fields)
    if not materialized_fields:
        raise DSLValidationError("input.fields must not be empty")
    for field in materialized_fields:
        if not _FIELD_PATTERN.match(field):
            raise DSLValidationError(f"invalid field name: {field}")
        if field not in available_fields:
            raise DSLValidationError(f"field not found in schema registry: {field}")


def _validate_expression(expr: str, max_ast_nodes: int, allow_empty: bool = False) -> None:
    normalized = expr.strip()
    if not normalized:
        if allow_empty:
            return
        raise DSLValidationError("condition.expr must not be empty")

    node_count = len([token for token in re.split(r"\s+", normalized) if token])
    if node_count > max_ast_nodes:
        raise DSLValidationError(f"expression too complex: ast nodes {node_count} > {max_ast_nodes}")

    if not any(operator in normalized for operator in _ALLOWED_OPERATORS):
        raise DSLValidationError("expression must contain at least one supported operator")

    disallowed_fn = re.findall(r"([a-zA-Z_][a-zA-Z0-9_]*)\(", normalized)
    for fn_name in disallowed_fn:
        if fn_name not in _ALLOWED_FUNCTIONS:
            raise DSLValidationError(f"function not allowed in phase-1: {fn_name}")


def _validate_action(action: ActionEffect) -> None:
    if not action.endpoint.startswith("action://"):
        raise DSLValidationError("effect.action.endpoint must use action:// scheme")
    required_tokens = ("${monitorId}", "${objectId}", "${sourceVersion}")
    if not all(token in action.idempotency_key for token in required_tokens):
        raise DSLValidationError("effect.action.idempotencyKey must contain monitor/object/version tokens")
