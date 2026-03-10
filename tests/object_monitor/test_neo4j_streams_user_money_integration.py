import os
import shutil
import subprocess
import tarfile
import time
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from neo4j import GraphDatabase

from ontology.action.storage.edits import AddObjectEdit, ModifyObjectEdit, ObjectLocator
from ontology.instance.storage.graph_store import Neo4jGraphStore
from ontology.object_monitor.compiler import build_monitor_artifact, parse_monitor_definition
from ontology.object_monitor.runtime import (
    ActionDispatcher,
    ActionGatewayResponse,
    ContextBuilder,
    EventFilter,
    L1Evaluator,
    MonitorRuntimeSpec,
    Neo4jStreamsEventMapper,
)
from ontology.object_monitor.runtime.reconcile import InMemoryReconcileQueue
from ontology.object_monitor.storage.sqlite_repository import SqliteActivityLedger, SqliteEvaluationLedger

NEO4J_VERSION = "4.4.48"
STREAMS_VERSION = "4.1.9"


class TagRichGateway:
    def __init__(self, graph_store: Neo4jGraphStore) -> None:
        self._graph_store = graph_store

    def apply_action(self, *, action_id: str, endpoint: str, payload: dict, idempotency_key: str) -> ActionGatewayResponse:
        user_id = str(payload["user_id"])
        self._graph_store.apply_edit(
            ModifyObjectEdit(
                locator=ObjectLocator(object_type="User", primary_key=user_id),
                properties={"tag": "rich"},
            )
        )
        return ActionGatewayResponse(status_code=200, execution_id=f"exec-{action_id}")


def _artifact():
    payload = {
        "monitor": {"id": "m_user_money_rich", "objectType": "User", "scope": ""},
        "input": {"fields": ["money", "tag"]},
        "condition": {"expr": "money > 100"},
        "effect": {
            "action": {
                "endpoint": "action://user/tag-rich",
                "idempotencyKey": "${monitorId}:${objectId}:${sourceVersion}:${actionId}",
            }
        },
    }
    return build_monitor_artifact(parse_monitor_definition(payload), monitor_version=1)


def _download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, target.open("wb") as out:
        shutil.copyfileobj(response, out)


def _wait_for_neo4j_ready(uri: str, user: str, password: str, timeout_seconds: int = 120) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with GraphDatabase.driver(uri, auth=(user, password)) as driver:
                with driver.session() as session:
                    if session.run("RETURN 1").single():
                        return
        except Exception:  # noqa: BLE001
            time.sleep(1)
    raise RuntimeError("Neo4j did not become ready within timeout")


def _best_effort_stop_neo4j(neo4j_bin: Path, neo4j_root: Path, env: dict[str, str]) -> None:
    subprocess.run(["pkill", "-f", str(neo4j_root)], check=False)
    time.sleep(1)


@contextmanager
def _runtime_neo4j_credentials():
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")
    if uri and user and password:
        yield uri, user, password
        return

    cache_root = Path(".cache/neo4j-test")
    archive_path = cache_root / f"neo4j-community-{NEO4J_VERSION}-unix.tar.gz"
    neo4j_root = cache_root / f"neo4j-community-{NEO4J_VERSION}"
    streams_jar = cache_root / f"neo4j-streams-{STREAMS_VERSION}.jar"

    if not archive_path.exists():
        _download(f"https://dist.neo4j.org/neo4j-community-{NEO4J_VERSION}-unix.tar.gz", archive_path)

    if not neo4j_root.exists():
        with tarfile.open(archive_path) as tar:
            tar.extractall(cache_root, filter="data")

    if not streams_jar.exists():
        _download(
            f"https://github.com/neo4j-contrib/neo4j-streams/releases/download/{STREAMS_VERSION}/"
            f"neo4j-streams-{STREAMS_VERSION}.jar",
            streams_jar,
        )

    installed_streams_jar = neo4j_root / "plugins" / streams_jar.name
    shutil.copy2(streams_jar, installed_streams_jar)

    conf_file = neo4j_root / "conf" / "neo4j.conf"
    conf_file.write_text(
        "\n".join(
            [
                "dbms.default_listen_address=127.0.0.1",
                "dbms.connector.bolt.listen_address=:17687",
                "dbms.connector.http.listen_address=:17474",
                "dbms.security.auth_enabled=true",
                "dbms.unmanaged_extension_classes=streams.kafka=streams.kafka,streams.events.source=streams.events.source",
                "kafka.bootstrap.servers=127.0.0.1:9092",
                "streams.source.enabled=true",
                "streams.sink.enabled=true",
                "streams.procedures.enabled=true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    neo4j_admin = (neo4j_root / "bin" / "neo4j-admin").resolve()
    neo4j_bin = (neo4j_root / "bin" / "neo4j").resolve()

    env = os.environ.copy()
    env["JAVA_HOME"] = "/usr/lib/jvm/java-11-openjdk-amd64"

    subprocess.run(
        [str(neo4j_admin), "set-initial-password", "test-password"],
        check=False,
        cwd=neo4j_root,
        env=env,
    )

    _best_effort_stop_neo4j(neo4j_bin, neo4j_root, env)
    start = subprocess.run([str(neo4j_bin), "start"], check=False, cwd=neo4j_root, env=env, capture_output=True, text=True)
    if start.returncode != 0 and "already running" not in ((start.stdout or "") + (start.stderr or "")):
        raise RuntimeError(f"Failed to start Neo4j: {(start.stdout or "").strip()} {(start.stderr or "").strip()}")

    uri = "bolt://127.0.0.1:17687"
    user = "neo4j"
    password = "test-password"
    try:
        _wait_for_neo4j_ready(uri, user, password)
        yield uri, user, password
    finally:
        _best_effort_stop_neo4j(neo4j_bin, neo4j_root, env)


def test_streams_money_update_triggers_action_and_updates_tag() -> None:
    with _runtime_neo4j_credentials() as (uri, user, password):
        store = Neo4jGraphStore(uri=uri, user=user, password=password)
        with store._driver.session() as session:
            session.run("MATCH (n:User) DETACH DELETE n")

        store.apply_edit(AddObjectEdit("User", "U100", {"money": 50, "tag": "poor"}))
        before = store.get_object(ObjectLocator("User", "U100"))

        store.apply_edit(ModifyObjectEdit(ObjectLocator("User", "U100"), {"money": 150}))
        after = store.get_object(ObjectLocator("User", "U100"))

        stream_message = {
            "meta": {
                "txId": after.version or 0,
                "txSeq": after.version or 0,
                "timestamp": datetime.utcnow().isoformat(),
            },
            "payload": {
                "before": {"properties": {"primary_key": "U100", **before.properties}},
                "after": {"properties": {"primary_key": "U100", **after.properties}},
            },
        }
        event = Neo4jStreamsEventMapper.from_streams_message(
            stream_message,
            tenant_id="t1",
            object_type="User",
            object_id_field="primary_key",
        )

        context_builder = ContextBuilder()
        context_builder.build(event, object_payload=after.properties)

        artifact = _artifact()
        event_filter = EventFilter()
        event_filter.load_specs([MonitorRuntimeSpec(artifact=artifact, object_type="User", watched_fields={"money"})])
        context_payload = context_builder.store.get("t1", "User", "U100").payload
        candidates = event_filter.filter_candidates(event, context_payload)
        assert len(candidates) == 1

        eval_ledger = SqliteEvaluationLedger(":memory:")
        reconcile = InMemoryReconcileQueue()
        evaluator = L1Evaluator(context_builder.store, eval_ledger, reconcile_queue=reconcile)
        evaluations = evaluator.evaluate_l1(event, candidates)

        assert len(evaluations) == 1
        assert evaluations[0].result.value == "HIT"

        activity_ledger = SqliteActivityLedger(":memory:")
        dispatcher = ActionDispatcher(TagRichGateway(store), activity_ledger)
        activity_id = dispatcher.dispatch(
            evaluations[0],
            action_id="user.tag.rich",
            endpoint="action://user/tag-rich",
            payload={"user_id": "U100"},
            idempotency_template=artifact.action_template["idempotency_key"],
        )

        activity = activity_ledger.get_activity(activity_id)
        assert activity.status == "succeeded"

        final_obj = store.get_object(ObjectLocator("User", "U100"))
        assert final_obj.properties["money"] == 150
        assert final_obj.properties["tag"] == "rich"
