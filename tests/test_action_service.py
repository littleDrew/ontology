from datetime import datetime

from ontology import (
    ActionDefinition,
    ActionRunner,
    ActionReconciler,
    ActionService,
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
    NotificationDispatcher,
    NotificationEffectHandler,
    WebhookDispatcher,
    WebhookEffectHandler,
)
from ontology.runtime import function_action
from ontology.edits import ModifyObjectEdit, ObjectLocator, TransactionEdit, edit_to_dict


@function_action
def update_status(loan: ObjectInstance, context, status: str) -> str:
    loan.status = status
    context.add_object("AuditEvent", "audit-2", {"status": status})
    return "ok"


def test_action_service_executes_and_emits_outbox() -> None:
    store = InMemoryGraphStore()
    store.add_object("Loan", "loan-2", {"status": "PENDING"})
    repo = InMemoryActionRepository()
    service = ActionService(repo, ActionRunner(), DataFunnelService(store))

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
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
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
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    repo.add_outbox(entry)

    worker.drain()
    assert repo.outbox["out-2"].status == "pending"
    assert repo.outbox["out-2"].retry_count == 1

    repo.outbox["out-2"].next_attempt_at = datetime.utcnow()
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
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    repo.add_action_state(state)

    reconciler.reconcile(cutoff_seconds=0)

    assert repo.action_states[action_id].status == ActionStateStatus.succeeded
    assert any(entry.effect_type == "notify" for entry in repo.outbox.values())


def test_action_service_saga_compensation() -> None:
    store = InMemoryGraphStore()
    store.add_object("Loan", "loan-3", {"status": "PENDING"})
    repo = InMemoryActionRepository()
    service = ActionService(repo, ActionRunner(), DataFunnelService(store))

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
    service = ActionService(repo, ActionRunner(), DataFunnelService(store))
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


def test_action_service_revert_records_revert() -> None:
    store = InMemoryGraphStore()
    store.add_object("Loan", "loan-6", {"status": "APPROVED"})
    repo = InMemoryActionRepository()
    service = ActionService(repo, ActionRunner(), DataFunnelService(store))

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
