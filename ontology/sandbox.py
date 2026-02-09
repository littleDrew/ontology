from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional


@dataclass
class BubblewrapConfig:
    python_executable: str = sys.executable
    network_enabled: bool = False
    read_only_root: bool = True
    timeout_s: float = 5.0


class BubblewrapRunner:
    def __init__(self, config: Optional[BubblewrapConfig] = None) -> None:
        self._config = config or BubblewrapConfig()

    @staticmethod
    def available() -> bool:
        return shutil.which("bwrap") is not None

    def build_command(self, script_path: Path) -> List[str]:
        cmd = ["bwrap", "--die-with-parent", "--unshare-all"]
        if self._config.read_only_root:
            cmd.extend(["--ro-bind", "/", "/"])
        else:
            cmd.extend(["--bind", "/", "/"])
        cmd.extend(["--proc", "/proc"])
        cmd.extend(["--dir", "/tmp"])
        if self._config.network_enabled:
            cmd.append("--share-net")
        cmd.extend([self._config.python_executable, str(script_path)])
        return cmd

    def run(self, module_path: str, function_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.available():
            raise RuntimeError("bubblewrap is not available")
        with tempfile.TemporaryDirectory() as workdir:
            workdir_path = Path(workdir)
            script_path = workdir_path / "sandbox_runner.py"
            script_path.write_text(
                _sandbox_script(module_path, function_name),
                encoding="utf-8",
            )
            input_data = json.dumps(payload).encode("utf-8")
            cmd = self.build_command(script_path)
            result = subprocess.run(
                cmd,
                input=input_data,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=self._config.timeout_s,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.decode("utf-8"))
            return json.loads(result.stdout.decode("utf-8"))


def _sandbox_script(module_path: str, function_name: str) -> str:
    return f"""
import json
import importlib
import sys

payload = json.loads(sys.stdin.read())
module = importlib.import_module({module_path!r})
fn = getattr(module, {function_name!r})
result = fn(**payload)
print(json.dumps({{'result': result}}))
"""
