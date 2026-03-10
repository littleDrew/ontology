import pytest

from ontology.action.utils import now_utc

from ontology import (
    ActionDefinition,
    ActionRunner,
    ActionReconciler,
    ActionService,
    ActionFeatureFlags,
    ActionExecutionMode,
    ActionTargetType,
    ActionState,
    ActionStateStatus,
    DataFunnelService,
    InMemoryActionRepository,
    InMemoryGraphStore,
    ObjectInstance,
    SagaStep,
    SideEffect,
    SideEffectOutbox,
    SideEffectRegistry,
    SideEffectWorker,
    FunctionDefinition,
    NotificationDispatcher,
    NotificationEffectHandler,
    WebhookDispatcher,
    WebhookEffectHandler,
)
from ontology.action.execution.runtime import function_action
from ontology.action.storage.edits import ModifyObjectEdit, ObjectLocator, RelationInstance, TransactionEdit, edit_to_dict


@function_action
def update_status(loan: ObjectInstance, context, status: str) -> str:
    loan.status = status
    context.add_object("AuditEvent", "audit-2", {"status": status})
    return "ok"


def test_action_service_executes_and_emits_outbox() -> None:
    store = InMemoryGraphStore()
    store.add_object("Loan", "loan-2", {"status": "PENDING"})
    repo = InMemoryActionRepository()
    service = ActionService(repo, ActionRunner(), DataFunnelService(store), feature_flags=ActionFeatureFlags(side_effects_enabled=True, saga_enabled=True, revert_enabled=True))

    definition = ActionDefinition(
        name="UpdateStatus",
        description="Update status",
        function_name="update_status",
        submission_criteria=lambda payload: payload["status"] in {"APPROVED", "REJECTED"},
    )

    execution = service.submit(
        definition=definition,
        submitter="user-1",
        input_payload={"status": "APPROVED"},
    )

    loan_instance = store.get_object(ObjectLocator("Loan", "loan-2"))
    service.execute(
        execution,
        definition,
        update_status,
        {"loan": loan_instance},
        side_effects=[SideEffect(effect_type="notify", payload={"message": "done"})],
    )

    updated = store.get_object(ObjectLocator("Loan", "loan-2"))
    assert updated.properties["status"] == "APPROVED"
    assert any(entry.effect_type == "notify" for entry in repo.outbox.values())
    event_types = [log.event_type for log in repo.logs if log.execution_id == execution.execution_id]
    assert "function_started" in event_types
    assert "function_finished" in event_types
    assert "apply_started" in event_types
    assert "apply_succeeded" in event_types


def test_side_effect_handlers_dispatch() -> None:
    registry = SideEffectRegistry()
    notifications = NotificationDispatcher()
    repo = InMemoryActionRepository()
    webhooks = WebhookDispatcher()

    registry.register("notify", NotificationEffectHandler(notifications, repo))
    registry.register("webhook", WebhookEffectHandler(webhooks))

    registry.handle(
        "notify",
        {"channel": "email", "subject": "Hi", "body": "There", "execution_id": "exec-1"},
    )
    assert notifications.sent[0].channel == "email"
    assert repo.notification_logs[0].execution_id == "exec-1"


def test_side_effect_worker_handles_outbox() -> None:
    repo = InMemoryActionRepository()
    registry = SideEffectRegistry()
    called = []

    def handler(payload):
        called.append(payload["message"])

    registry.register("notify", handler)
    worker = SideEffectWorker(repo, registry)
    repo.add_outbox(
        SideEffectOutbox(
            outbox_id="out-1",
            execution_id="exec-1",
            effect_type="notify",
            payload={"message": "hello"},
            created_at=now_utc(),
            updated_at=now_utc(),
        )
    )
    worker.drain()
    assert called == ["hello"]


def test_side_effect_worker_applies_backoff_and_dead_letter() -> None:
    repo = InMemoryActionRepository()
    registry = SideEffectRegistry()

    def handler(payload):
        raise ValueError("fail")

    registry.register("notify", handler)
    worker = SideEffectWorker(repo, registry)
    entry = SideEffectOutbox(
        outbox_id="out-2",
        execution_id="exec-2",
        effect_type="notify",
        payload={"message": "hello"},
        max_retries=2,
        created_at=now_utc(),
        updated_at=now_utc(),
    )
    repo.add_outbox(entry)

    worker.drain()
    assert repo.outbox["out-2"].status == "pending"
    assert repo.outbox["out-2"].retry_count == 1

    repo.outbox["out-2"].next_attempt_at = now_utc()
    worker.drain()
    assert repo.outbox["out-2"].status == "dead_letter"


def test_action_reconciler_backfills_outbox() -> None:
    store = InMemoryGraphStore()
    store.add_object("Loan", "loan-4", {"status": "PENDING"})
    repo = InMemoryActionRepository()
    apply_engine = DataFunnelService(store)
    reconciler = ActionReconciler(repo, apply_engine)

    edit = TransactionEdit(
        edits=[ModifyObjectEdit(locator=ObjectLocator("Loan", "loan-4"), properties={"status": "APPROVED"})]
    )
    action_id = "exec-42"
    apply_engine.apply(edit, action_id=action_id)

    state = ActionState(
        action_id=action_id,
        execution_id=action_id,
        status=ActionStateStatus.pending,
        intent_payload={
            "edits": edit_to_dict(edit),
            "side_effects": [{"effect_type": "notify", "payload": {"message": "done"}}],
        },
        created_at=now_utc(),
        updated_at=now_utc(),
    )
    repo.add_action_state(state)

    reconciler.reconcile(cutoff_seconds=0)

    assert repo.action_states[action_id].status == ActionStateStatus.succeeded
    assert any(entry.effect_type == "notify" for entry in repo.outbox.values())


def test_action_service_saga_compensation() -> None:
    store = InMemoryGraphStore()
    store.add_object("Loan", "loan-3", {"status": "PENDING"})
    repo = InMemoryActionRepository()
    service = ActionService(repo, ActionRunner(), DataFunnelService(store), feature_flags=ActionFeatureFlags(side_effects_enabled=True, saga_enabled=True, revert_enabled=True))

    def compensate(instances, payload):
        loan = instances["loan"]
        return TransactionEdit(
            edits=[
                ModifyObjectEdit(
                    locator=ObjectLocator("Loan", loan.primary_key, version=loan.version),
                    properties={"status": "REVERTED"},
                )
            ]
        )

    def failing_action(loan: ObjectInstance, context, status: str) -> str:
        loan.status = status
        raise ValueError("boom")

    definition = ActionDefinition(
        name="FailingAction",
        description="Fails and compensates",
        function_name="failing_action",
        compensation_fn=compensate,
    )

    execution = service.submit(
        definition=definition,
        submitter="user-2",
        input_payload={"status": "APPROVED"},
    )
    loan_instance = store.get_object(ObjectLocator("Loan", "loan-3"))
    execution = service.execute(execution, definition, failing_action, {"loan": loan_instance})

    updated = store.get_object(ObjectLocator("Loan", "loan-3"))
    assert updated.properties["status"] == "REVERTED"
    assert execution.status.value == "reverted"


def test_action_service_saga_steps_compensate_external() -> None:
    store = InMemoryGraphStore()
    store.add_object("Loan", "loan-4", {"status": "PENDING"})
    repo = InMemoryActionRepository()
    service = ActionService(repo, ActionRunner(), DataFunnelService(store), feature_flags=ActionFeatureFlags(side_effects_enabled=True, saga_enabled=True, revert_enabled=True))
    external_log = []

    def step_one(instances, payload):
        external_log.append("writeback-1")

    def step_one_compensate(instances, payload):
        external_log.append("compensate-1")

    def step_two(instances, payload):
        external_log.append("writeback-2")
        raise ValueError("external fail")

    def step_two_compensate(instances, payload):
        external_log.append("compensate-2")

    def action_ok(loan: ObjectInstance, context, status: str) -> str:
        loan.status = status
        return "ok"

    definition = ActionDefinition(
        name="SagaAction",
        description="Saga with external writes",
        function_name="action_ok",
        saga_steps=[
            SagaStep(name="step1", action=step_one, compensation=step_one_compensate),
            SagaStep(name="step2", action=step_two, compensation=step_two_compensate),
        ],
    )

    execution = service.submit(
        definition=definition,
        submitter="user-3",
        input_payload={"status": "APPROVED"},
    )
    loan_instance = store.get_object(ObjectLocator("Loan", "loan-4"))
    execution = service.execute(execution, definition, action_ok, {"loan": loan_instance})

    assert execution.status.value == "failed"
    assert external_log == ["writeback-1", "writeback-2", "compensate-2", "compensate-1"]
    failure_logs = [log for log in repo.logs if log.execution_id == execution.execution_id and log.event_type == "execution_failed"]
    assert len(failure_logs) == 1
    assert failure_logs[0].payload["failed_stage"] in {"executing", "applying"}


def test_action_service_revert_records_revert() -> None:
    store = InMemoryGraphStore()
    store.add_object("Loan", "loan-6", {"status": "APPROVED"})
    repo = InMemoryActionRepository()
    service = ActionService(repo, ActionRunner(), DataFunnelService(store), feature_flags=ActionFeatureFlags(side_effects_enabled=True, saga_enabled=True, revert_enabled=True))

    execution = service.submit(
        definition=ActionDefinition(
            name="Revertable",
            description="Manual revert",
            function_name="noop",
        ),
        submitter="user-4",
        input_payload={},
    )
    execution.compensation_edit = TransactionEdit(
        edits=[
            ModifyObjectEdit(
                locator=ObjectLocator("Loan", "loan-6", version=1),
                properties={"status": "REVERTED"},
            )
        ]
    )
    service.revert(execution)

    updated = store.get_object(ObjectLocator("Loan", "loan-6"))
    assert updated.properties["status"] == "REVERTED"
    assert repo.reverts[-1].original_execution_id == execution.execution_id


def test_phase2_features_disabled_by_default() -> None:
    store = InMemoryGraphStore()
    store.add_object("Loan", "loan-100", {"status": "PENDING"})
    repo = InMemoryActionRepository()
    service = ActionService(repo, ActionRunner(), DataFunnelService(store))

    definition = ActionDefinition(
        name="UpdateNoSideEffect",
        description="Update status",
        function_name="update_status",
    )

    execution = service.submit(
        definition=definition,
        submitter="user-1",
        input_payload={"status": "APPROVED"},
    )

    loan_instance = store.get_object(ObjectLocator("Loan", "loan-100"))
    service.execute(
        execution,
        definition,
        update_status,
        {"loan": loan_instance},
        side_effects=[SideEffect(effect_type="notify", payload={"message": "done"})],
    )

    assert repo.outbox == {}


def test_action_service_apply_uses_sandbox_mode_result_protocol() -> None:
    class StubFunctionRuntime:
        def execute_in_sandbox(self, implementation_code, function_name, input_instances, params=None, metadata=None):
            assert implementation_code == "def update_status(loan, context, status):\n    loan.status = status\n    return 'ok'"
            assert function_name == "update_status"
            return {
                "result": "ok",
                "edits": TransactionEdit(
                    edits=[
                        ModifyObjectEdit(
                            locator=ObjectLocator("Loan", "loan-sbx"),
                            properties={"status": "APPROVED"},
                        )
                    ]
                ),
            }

    store = InMemoryGraphStore()
    store.add_object("Loan", "loan-sbx", {"status": "PENDING"})
    repo = InMemoryActionRepository()
    runner = ActionRunner()
    service = ActionService(
        repo,
        runner,
        DataFunnelService(store),
        function_runtime=StubFunctionRuntime(),
    )

    repo.add_function(
        FunctionDefinition(
            name="update_status",
            runtime="python",
            code_ref="def update_status(loan, context, status):\n    loan.status = status\n    return 'ok'",
            version=1,
        )
    )
    definition = ActionDefinition(
        name="SandboxAction",
        description="Sandbox action",
        function_name="update_status",
        execution_mode=ActionExecutionMode.sandbox,
        version=1,
    )
    repo.add_action(definition)

    execution = service.apply(
        action_name="SandboxAction",
        submitter="user-sbx",
        input_payload={"status": "APPROVED"},
        version=1,
        input_instance_locators={"loan": {"object_type": "Loan", "primary_key": "loan-sbx"}},
    )

    assert execution.status.value == "succeeded"
    updated = store.get_object(ObjectLocator("Loan", "loan-sbx"))
    assert updated.properties["status"] == "APPROVED"


def test_action_service_sandbox_resolves_function_version_independently() -> None:
    class StubFunctionRuntime:
        def execute_in_sandbox(self, implementation_code, function_name, input_instances, params=None, metadata=None):
            assert implementation_code == "def update_status_v2(loan, context, status):\n    loan.status = status\n    return 'ok-v2'"
            return {
                "result": "ok-v2",
                "edits": TransactionEdit(
                    edits=[
                        ModifyObjectEdit(
                            locator=ObjectLocator("Loan", "loan-sbx-v2"),
                            properties={"status": "APPROVED"},
                        )
                    ]
                ),
            }

    store = InMemoryGraphStore()
    store.add_object("Loan", "loan-sbx-v2", {"status": "PENDING"})
    repo = InMemoryActionRepository()
    service = ActionService(
        repo,
        ActionRunner(),
        DataFunnelService(store),
        function_runtime=StubFunctionRuntime(),
    )

    # Register only function version 2 while action version is 1.
    repo.add_function(
        FunctionDefinition(
            name="update_status",
            runtime="python",
            code_ref="def update_status_v2(loan, context, status):\n    loan.status = status\n    return 'ok-v2'",
            version=2,
        )
    )
    repo.add_action(
        ActionDefinition(
            name="SandboxActionV2",
            description="Sandbox action v2",
            function_name="update_status",
            execution_mode=ActionExecutionMode.sandbox,
            version=1,
        )
    )

    execution = service.apply(
        action_name="SandboxActionV2",
        submitter="user-sbx",
        input_payload={"status": "APPROVED"},
        version=1,
        input_instance_locators={"loan": {"object_type": "Loan", "primary_key": "loan-sbx-v2"}},
    )

    assert execution.status.value == "succeeded"


def test_action_service_validates_entity_target_type() -> None:
    store = InMemoryGraphStore()
    store.add_object("Loan", "loan-t1", {"status": "PENDING"})
    repo = InMemoryActionRepository()
    service = ActionService(repo, ActionRunner(), DataFunnelService(store))

    definition = ActionDefinition(
        name="EntityTarget",
        description="Entity target",
        function_name="noop",
        target_type=ActionTargetType.entity,
        target_api_name="Borrower",
        version=1,
    )
    repo.add_action(definition)
    repo.add_function(FunctionDefinition(name="noop", runtime="python", code_ref="def noop(context): return 'ok'", version=1))

    with pytest.raises(ValueError, match="does not match target_api_name"):
        service.apply(
            action_name="EntityTarget",
            submitter="u",
            input_payload={},
            version=1,
            input_instance_locators={"loan": {"object_type": "Loan", "primary_key": "loan-t1"}},
        )


def test_action_service_resolves_relation_input_and_validates_relation_target_type() -> None:
    store = InMemoryGraphStore()
    store.add_object("User", "u1", {"name": "A"})
    store.add_object("Group", "g1", {"name": "B"})
    repo = InMemoryActionRepository()
    service = ActionService(repo, ActionRunner(), DataFunnelService(store))

    captured = {}

    def relation_action(membership: RelationInstance, context):
        captured["link_type"] = membership.link_type
        return "ok"

    runner = ActionRunner()
    runner.register("relation_action", relation_action)
    service = ActionService(repo, runner, DataFunnelService(store))

    definition = ActionDefinition(
        name="RelationTarget",
        description="Relation target",
        function_name="relation_action",
        target_type=ActionTargetType.relation,
        target_api_name="MEMBER_OF",
        version=1,
    )
    repo.add_action(definition)

    execution = service.apply(
        action_name="RelationTarget",
        submitter="u",
        input_payload={},
        version=1,
        input_instance_locators={
            "membership": {
                "link_type": "MEMBER_OF",
                "from": {"object_type": "User", "primary_key": "u1"},
                "to": {"object_type": "Group", "primary_key": "g1"},
            }
        },
    )

    assert execution.status.value == "succeeded"
    assert captured["link_type"] == "MEMBER_OF"
