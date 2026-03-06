from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional

from ..storage.edits import edit_from_dict


class SandboxExecutionError(RuntimeError):
    """Raised when sandbox process exits with an execution error."""


class SandboxTimeoutError(RuntimeError):
    """Raised when sandbox execution exceeds configured timeout."""


@dataclass
class BubblewrapConfig:
    """Configuration for bubblewrap sandbox execution constraints."""
    python_executable: str = sys.executable
    network_enabled: bool = False
    read_only_root: bool = True
    timeout_s: float = 5.0


class BubblewrapRunner:
    """Execute function modules/code in bubblewrap-isolated subprocesses."""
    def __init__(self, config: Optional[BubblewrapConfig] = None) -> None:
        self._config = config or BubblewrapConfig()

    @staticmethod
    def available() -> bool:
        return shutil.which("bwrap") is not None

    def build_command(self, script_path: Path, workdir: Path) -> List[str]:
        cmd = ["bwrap", "--die-with-parent", "--unshare-all"]
        if self._config.read_only_root:
            cmd.extend(["--ro-bind", "/", "/"])
        else:
            cmd.extend(["--bind", "/", "/"])
        cmd.extend(["--proc", "/proc"])
        cmd.extend(["--tmpfs", "/tmp"])
        cmd.extend(["--bind", str(workdir), "/workspace"])
        cmd.extend(["--chdir", "/workspace"])
        if self._config.network_enabled:
            cmd.append("--share-net")
        cmd.extend([self._config.python_executable, f"/workspace/{script_path.name}"])
        return cmd

    def _run_process(self, cmd: List[str], input_data: bytes, cwd: Path) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                cmd,
                input=input_data,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=self._config.timeout_s,
                cwd=str(cwd),
            )
        except subprocess.TimeoutExpired as exc:
            raise SandboxTimeoutError(
                f"sandbox execution timed out after {self._config.timeout_s:.2f}s"
            ) from exc

    def run_sandboxed_code(self, implementation_code: str, function_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.available():
            raise RuntimeError("bubblewrap is not available")
        with tempfile.TemporaryDirectory() as workdir:
            workdir_path = Path(workdir)
            module_path = workdir_path / "user_function.py"
            module_path.write_text(implementation_code, encoding="utf-8")
            script_path = workdir_path / "sandbox_runner.py"
            repo_root = str(Path(__file__).resolve().parents[3])
            script_path.write_text(
                _sandbox_script("user_function", function_name, repo_root),
                encoding="utf-8",
            )
            input_data = json.dumps(payload).encode("utf-8")
            cmd = self.build_command(script_path, workdir_path)
            result = self._run_process(cmd, input_data=input_data, cwd=workdir_path)
            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace").strip()
                raise SandboxExecutionError(stderr or f"sandbox exited with code {result.returncode}")
            try:
                output = json.loads(result.stdout.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise SandboxExecutionError("sandbox returned malformed JSON payload") from exc
            if "edits" in output:
                output["edits"] = edit_from_dict(output["edits"])
            return output


def _sandbox_script(module_path: str, function_name: str, repo_root: str) -> str:
    return f"""
import json
import importlib
import sys

sys.path.insert(0, {repo_root!r})

from ontology.action.execution.runtime import ActionRunner
from ontology.action.storage.edits import ObjectInstance, ObjectLocator, RelationInstance, edit_to_dict

payload = json.loads(sys.stdin.read())
module = importlib.import_module({module_path!r})
fn = getattr(module, {function_name!r})
input_instances = {{}}
for name, item in payload.get("input_instances", {{}}).items():
    kind = item.get("kind", "entity")
    if kind == "relation":
        input_instances[name] = RelationInstance(
            link_type=item["link_type"],
            from_locator=ObjectLocator(
                object_type=item["from"]["object_type"],
                primary_key=item["from"]["primary_key"],
                version=item["from"].get("version"),
            ),
            to_locator=ObjectLocator(
                object_type=item["to"]["object_type"],
                primary_key=item["to"]["primary_key"],
                version=item["to"].get("version"),
            ),
        )
    else:
        input_instances[name] = ObjectInstance(
            object_type=item["object_type"],
            primary_key=item["primary_key"],
            properties=item.get("properties", {{}}),
            version=item.get("version"),
        )
params = payload.get("params", {{}})
metadata = payload.get("metadata", {{}})
execution = ActionRunner().execute(fn, input_instances, params=params, metadata=metadata)
print(json.dumps({{"result": execution["result"], "edits": edit_to_dict(execution["edits"])}}))
"""
