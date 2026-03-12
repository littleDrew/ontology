from __future__ import annotations

from ontology.action.api.domain_models import FunctionDefinition
from ontology.action.api.service import ActionService
from ontology.action.execution.runtime import ActionRunner, function_action
from ontology.action.storage.repository import InMemoryActionRepository
from ontology.instance.api.service import InstanceService
from ontology.instance.storage.graph_store import InMemoryGraphStore
from ontology.main import create_app
from ontology.object_monitor.runtime.api.data_plane_app import ObjectMonitorDataPlaneService, create_object_monitor_data_plane_app
from ontology.object_monitor.runtime.action_gateway_adapter import OntologyActionApiAdapter
from ontology.object_monitor.runtime.action_dispatcher import ActionDispatcher
from ontology.object_monitor.runtime.capture.normalizer import ChangeNormalizer
from ontology.object_monitor.runtime.capture.pipeline import SingleChannelIngestionPipeline
from ontology.object_monitor.runtime.capture.raw_consumer import KafkaConsumerConfig, KafkaRawConsumerRunner, RawConsumerRuntime
from ontology.object_monitor.runtime.context_builder import ContextBuilder
from ontology.object_monitor.runtime.event_filter import EventFilter
from ontology.object_monitor.runtime.evaluator import L1Evaluator
from ontology.object_monitor.runtime.storage.activity_repository import InMemoryActivityLedger
from ontology.object_monitor.runtime.storage.repository import InMemoryEvaluationLedger


@function_action
def noop_action(context, **kwargs):
    return {"accepted": True, "input": kwargs}


def build_ontology_main_server_app():
    store = InMemoryGraphStore()
    repository = InMemoryActionRepository()
    runner = ActionRunner()
    runner.register("noop_action", noop_action)
    repository.add_function(FunctionDefinition(name="noop_action", runtime="python", code_ref="builtin://noop_action"))
    action_service = ActionService(repository=repository, runner=runner, apply_engine=InstanceService(store))
    app = create_app(store, action_service=action_service, repository=repository)
    return app


def build_object_monitor_data_plane_app(
    action_base_url: str = "http://127.0.0.1:8765",
    kafka_bootstrap_servers: str | None = None,
    kafka_topic: str = "object_change_raw",
    kafka_group_id: str = "object-monitor-runtime",
):
    service = build_object_monitor_data_plane_service(
        action_base_url=action_base_url,
        kafka_bootstrap_servers=kafka_bootstrap_servers,
        kafka_topic=kafka_topic,
        kafka_group_id=kafka_group_id,
    )
    return create_object_monitor_data_plane_app(service)


def build_object_monitor_data_plane_service(
    action_base_url: str = "http://127.0.0.1:8765",
    kafka_bootstrap_servers: str | None = None,
    kafka_topic: str = "object_change_raw",
    kafka_group_id: str = "object-monitor-runtime",
) -> ObjectMonitorDataPlaneService:
    context_builder = ContextBuilder()
    event_filter = EventFilter()
    eval_ledger = InMemoryEvaluationLedger()
    activity_ledger = InMemoryActivityLedger()
    evaluator = L1Evaluator(context_builder.store, eval_ledger)
    dispatcher = ActionDispatcher(OntologyActionApiAdapter(base_url=action_base_url), activity_ledger)

    service = ObjectMonitorDataPlaneService(
        context_builder=context_builder,
        event_filter=event_filter,
        evaluator=evaluator,
        dispatcher=dispatcher,
        evaluation_ledger=eval_ledger,
        activity_ledger=activity_ledger,
        raw_consumer=None,
        kafka_runner=None,
    )
    service.raw_consumer = RawConsumerRuntime(
        pipeline=SingleChannelIngestionPipeline(ChangeNormalizer(dedupe_window_seconds=30)),
        event_handler=lambda event: service.process_event(event),
    )
    if kafka_bootstrap_servers:
        service.kafka_runner = KafkaRawConsumerRunner(
            runtime=service.raw_consumer,
            config=KafkaConsumerConfig(
                bootstrap_servers=kafka_bootstrap_servers,
                topic=kafka_topic,
                group_id=kafka_group_id,
            ),
        )
    return service


def build_object_monitor_server_app(
    action_base_url: str = "http://127.0.0.1:8765",
    data_plane_base_url: str = "http://127.0.0.1:8771",
    kafka_bootstrap_servers: str | None = None,
    kafka_topic: str = "object_change_raw",
    kafka_group_id: str = "object-monitor-runtime",
):
    _ = data_plane_base_url
    data_plane_service = build_object_monitor_data_plane_service(
        action_base_url=action_base_url,
        kafka_bootstrap_servers=kafka_bootstrap_servers,
        kafka_topic=kafka_topic,
        kafka_group_id=kafka_group_id,
    )
    return create_object_monitor_data_plane_app(data_plane_service)
