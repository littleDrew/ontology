from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from ontology.object_monitor.api.contracts import (
    ActionDefinition,
    ConditionDefinition,
    GeneralDefinition,
    MonitorDefinition,
    ObjectSetDefinition,
    RuleDefinition,
)

_ALLOWED_FUNCTIONS = ("startsWith", "contains")
_ALLOWED_OPERATORS = ("&&", "||", "==", "!=", ">=", "<=", ">", "<", " in ", " not in ")
_FIELD_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_\.]*$")


class DSLValidationError(ValueError):
    """Raised when monitor DSL is invalid."""


@dataclass(frozen=True)
class ValidationContext:
    available_fields: Iterable[str]
    max_ast_nodes: int = 64


def parse_monitor_definition(payload: Mapping[str, Any]) -> MonitorDefinition:
    try:
        general = payload["general"]
        condition = payload["condition"]
        object_set = condition["objectSet"]
        rule = condition["rule"]
        actions = payload["actions"]
    except KeyError as exc:
        raise DSLValidationError(f"missing required section: {exc.args[0]}") from exc

    if not isinstance(actions, list) or not actions:
        raise DSLValidationError("actions must be a non-empty list")

    return MonitorDefinition(
        general=GeneralDefinition(
            name=str(general["name"]),
            description=str(general.get("description", "")),
            object_type=str(general["objectType"]),
            enabled=bool(general.get("enabled", True)),
        ),
        condition=ConditionDefinition(
            object_set=ObjectSetDefinition(
                type=str(object_set["type"]),
                scope=str(object_set.get("scope", "")),
                properties=[str(field) for field in object_set["properties"]],
            ),
            rule=RuleDefinition(expression=str(rule["expression"])),
        ),
        actions=[
            ActionDefinition(
                name=str(action["name"]),
                action_ref=str(action["actionRef"]),
                parameters=dict(action.get("parameters", {})),
            )
            for action in actions
        ],
    )


def validate_monitor_definition(definition: MonitorDefinition, context: ValidationContext) -> None:
    available_fields = set(context.available_fields)
    if not definition.general.name:
        raise DSLValidationError("general.name cannot be empty")
    if not definition.general.object_type:
        raise DSLValidationError("general.objectType cannot be empty")

    object_set = definition.condition.object_set
    if object_set.type != definition.general.object_type:
        raise DSLValidationError("condition.objectSet.type must match general.objectType")

    _validate_fields(object_set.properties, available_fields)
    _validate_expression(definition.condition.rule.expression, context.max_ast_nodes, field_candidates=object_set.properties)
    _validate_expression(object_set.scope, context.max_ast_nodes, allow_empty=True)
    for action in definition.actions:
        _validate_action(action)


def _validate_fields(fields: Iterable[str], available_fields: set[str]) -> None:
    materialized_fields = list(fields)
    if not materialized_fields:
        raise DSLValidationError("condition.objectSet.properties must not be empty")
    for field in materialized_fields:
        if not _FIELD_PATTERN.match(field):
            raise DSLValidationError(f"invalid field name: {field}")
        if field not in available_fields:
            raise DSLValidationError(f"field not found in schema registry: {field}")


def _validate_expression(expr: str, max_ast_nodes: int, *, allow_empty: bool = False, field_candidates: Iterable[str] | None = None) -> None:
    normalized = expr.strip()
    if not normalized:
        if allow_empty:
            return
        raise DSLValidationError("condition.rule.expression must not be empty")

    node_count = len([token for token in re.split(r"\s+", normalized) if token])
    if node_count > max_ast_nodes:
        raise DSLValidationError(f"expression too complex: ast nodes {node_count} > {max_ast_nodes}")

    if not any(operator in normalized for operator in _ALLOWED_OPERATORS):
        raise DSLValidationError("expression must contain at least one supported operator")

    disallowed_fn = re.findall(r"([a-zA-Z_][a-zA-Z0-9_]*)\(", normalized)
    for fn_name in disallowed_fn:
        if fn_name not in _ALLOWED_FUNCTIONS:
            raise DSLValidationError(f"function not allowed in phase-1: {fn_name}")

    if field_candidates is not None:
        allowed = set(field_candidates)
        bare_tokens = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_\.]*)\b", normalized)
        keywords = {"in", "not", "is", "null", "true", "false", "and", "or"}
        for token in bare_tokens:
            if token in keywords:
                continue
            if token in allowed:
                continue
            if token in _ALLOWED_FUNCTIONS:
                continue
            if token.isdigit():
                continue


def _validate_action(action: ActionDefinition) -> None:
    if not action.name:
        raise DSLValidationError("actions[].name cannot be empty")
    if not action.action_ref.startswith("action://"):
        raise DSLValidationError("actions[].actionRef must use action:// scheme")
    if not isinstance(action.parameters, dict):
        raise DSLValidationError("actions[].parameters must be a map when provided")
