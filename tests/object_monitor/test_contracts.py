from ontology.object_monitor.compiler import (
    DSLValidationError,
    ValidationContext,
    build_monitor_artifact,
    parse_monitor_definition,
    validate_monitor_definition,
)


def _sample_payload() -> dict:
    return {
        "general": {
            "name": "m_high_temp",
            "description": "high temp",
            "objectType": "Device",
            "enabled": True,
        },
        "condition": {
            "objectSet": {
                "type": "Device",
                "scope": "plant_id in ['P1','P2']",
                "properties": ["temperature", "status", "plant_id"],
            },
            "rule": {"expression": "temperature >= 80 && status == 'RUNNING'"},
        },
        "actions": [
            {
                "name": "create_ticket",
                "actionRef": "action://ticket/create",
                "parameters": {"severity": "high"},
            }
        ],
    }


def test_w1_compile_monitor_artifact_is_stable() -> None:
    definition = parse_monitor_definition(_sample_payload())
    ctx = ValidationContext(available_fields={"temperature", "status", "plant_id"})
    validate_monitor_definition(definition, ctx)

    artifact_1 = build_monitor_artifact(definition, monitor_version=3)
    artifact_2 = build_monitor_artifact(definition, monitor_version=3)

    assert artifact_1.plan_hash == artifact_2.plan_hash
    assert artifact_1.field_projection == ["plant_id", "status", "temperature"]
    assert artifact_1.rule_predicate_ast["phase"] == "L1"


def test_w1_validate_rejects_unregistered_field() -> None:
    payload = _sample_payload()
    payload["condition"]["objectSet"]["properties"] = ["temperature", "status", "not_exists"]
    definition = parse_monitor_definition(payload)

    ctx = ValidationContext(available_fields={"temperature", "status"})
    try:
        validate_monitor_definition(definition, ctx)
        assert False, "expected DSLValidationError"
    except DSLValidationError as exc:
        assert "field not found" in str(exc)


def test_w1_validate_rejects_invalid_action_scheme() -> None:
    payload = _sample_payload()
    payload["actions"][0]["actionRef"] = "http://ticket/create"
    definition = parse_monitor_definition(payload)

    ctx = ValidationContext(available_fields={"temperature", "status", "plant_id"})
    try:
        validate_monitor_definition(definition, ctx)
        assert False, "expected DSLValidationError"
    except DSLValidationError as exc:
        assert "actionRef" in str(exc)
