import os
import shutil
import subprocess
import tarfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest
from neo4j import GraphDatabase

NEO4J_VERSION = "4.4.48"
STREAMS_VERSION = "4.1.9"


def _run_best_effort(cmd: list[str], *, cwd: Path, env: dict[str, str], timeout_seconds: int = 20) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(cmd, check=False, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        return None


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


def _best_effort_stop_neo4j(neo4j_root: Path, env: dict[str, str]) -> None:
    neo4j_bin = (neo4j_root / "bin" / "neo4j").resolve()
    _run_best_effort([str(neo4j_bin), "stop"], cwd=neo4j_root, env=env)
    subprocess.run(["pkill", "-f", str(neo4j_root)], check=False)
    pid_file = neo4j_root / "run" / "neo4j.pid"
    if pid_file.exists():
        pid_file.unlink()
    time.sleep(1)


@contextmanager
def runtime_neo4j_credentials():
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

    shutil.copy2(streams_jar, neo4j_root / "plugins" / streams_jar.name)

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
    if not Path(env["JAVA_HOME"]).exists():
        pytest.skip("JAVA_HOME for embedded Neo4j is unavailable in current environment")

    _run_best_effort([str(neo4j_admin), "set-initial-password", "test-password"], cwd=neo4j_root, env=env)

    _best_effort_stop_neo4j(neo4j_root, env)
    start = subprocess.run([str(neo4j_bin), "start"], check=False, cwd=neo4j_root, env=env, capture_output=True, text=True)
    if start.returncode != 0 and "already running" not in ((start.stdout or "") + (start.stderr or "")):
        raise RuntimeError(f"Failed to start Neo4j: {(start.stdout or '').strip()} {(start.stderr or '').strip()}")

    try:
        uri = "bolt://127.0.0.1:17687"
        user = "neo4j"
        password = "test-password"
        _wait_for_neo4j_ready(uri, user, password)
        yield uri, user, password
    finally:
        _best_effort_stop_neo4j(neo4j_root, env)
