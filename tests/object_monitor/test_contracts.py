from ontology.object_monitor.compiler import (
    DSLValidationError,
    ValidationContext,
    build_monitor_artifact,
    parse_monitor_definition,
    validate_monitor_definition,
)


def _sample_payload() -> dict:
    return {
        "monitor": {
            "id": "m_high_temp",
            "objectType": "Device",
            "scope": "plant_id in ['P1','P2']",
        },
        "input": {"fields": ["temperature", "status", "plant_id"]},
        "condition": {"expr": "temperature >= 80 && status == 'RUNNING'"},
        "effect": {
            "action": {
                "endpoint": "action://ticket/create",
                "idempotencyKey": "${monitorId}:${objectId}:${sourceVersion}",
            }
        },
    }


def test_w1_compile_monitor_artifact_is_stable() -> None:
    definition = parse_monitor_definition(_sample_payload())
    ctx = ValidationContext(available_fields={"temperature", "status", "plant_id"})
    validate_monitor_definition(definition, ctx)

    artifact_1 = build_monitor_artifact(definition, monitor_version=3)
    artifact_2 = build_monitor_artifact(definition, monitor_version=3)

    assert artifact_1.plan_hash == artifact_2.plan_hash
    assert artifact_1.field_projection == ["plant_id", "status", "temperature"]
    assert artifact_1.predicate_ast["phase"] == "L1"


def test_w1_validate_rejects_unregistered_field() -> None:
    payload = _sample_payload()
    payload["input"]["fields"] = ["temperature", "status", "not_exists"]
    definition = parse_monitor_definition(payload)

    ctx = ValidationContext(available_fields={"temperature", "status"})
    try:
        validate_monitor_definition(definition, ctx)
        assert False, "expected DSLValidationError"
    except DSLValidationError as exc:
        assert "field not found" in str(exc)


def test_w1_validate_requires_idempotency_tokens() -> None:
    payload = _sample_payload()
    payload["effect"]["action"]["idempotencyKey"] = "${monitorId}:${objectId}"
    definition = parse_monitor_definition(payload)

    ctx = ValidationContext(available_fields={"temperature", "status", "plant_id"})
    try:
        validate_monitor_definition(definition, ctx)
        assert False, "expected DSLValidationError"
    except DSLValidationError as exc:
        assert "idempotencyKey" in str(exc)
