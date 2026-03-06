from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from ontology.action.execution.sandbox import BubblewrapRunner, SandboxExecutionError, SandboxTimeoutError


def test_bubblewrap_build_command_binds_workdir() -> None:
    runner = BubblewrapRunner()
    workdir = Path("/tmp/workdir")
    script = workdir / "sandbox_runner.py"

    cmd = runner.build_command(script, workdir)

    assert "--bind" in cmd
    assert str(workdir) in cmd
    assert "/workspace" in cmd
    assert "/workspace/sandbox_runner.py" in cmd


def test_bubblewrap_runner_executes_via_external_bwrap(tmp_path, monkeypatch) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_bwrap = fake_bin / "bwrap"
    fake_bwrap.write_text(
        "#!/usr/bin/env python3\n"
        "import os, subprocess, sys\n"
        "args = sys.argv[1:]\n"
        "binds = []\n"
        "i = 0\n"
        "while i < len(args):\n"
        "    if args[i] in {'--die-with-parent', '--unshare-all', '--share-net'}:\n"
        "        i += 1\n"
        "    elif args[i] in {'--ro-bind', '--bind'}:\n"
        "        binds.append((args[i + 1], args[i + 2]))\n"
        "        i += 3\n"
        "    elif args[i] in {'--proc', '--tmpfs', '--dir'}:\n"
        "        i += 2\n"
        "    elif args[i] == '--chdir':\n"
        "        os.chdir(args[i + 1])\n"
        "        i += 2\n"
        "    else:\n"
        "        break\n"
        "child = args[i:]\n"
        "for idx, token in enumerate(child):\n"
        "    for src, dst in binds:\n"
        "        if token == dst:\n"
        "            child[idx] = src\n"
        "            break\n"
        "        if token.startswith(dst + '/'):\n"
        "            child[idx] = src + token[len(dst):]\n"
        "            break\n"
        "if not child:\n"
        "    raise SystemExit('missing child command')\n"
        "proc = subprocess.run(child, input=sys.stdin.buffer.read(), stdout=sys.stdout.buffer, stderr=sys.stderr.buffer, check=False)\n"
        "raise SystemExit(proc.returncode)\n",
        encoding="utf-8",
    )
    fake_bwrap.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")

    implementation_code = (
        "def approve(loan, context, status):\n"
        "    loan.status = status\n"
        "    return {'ok': True}\n"
    )
    payload = {
        "input_instances": {
            "loan": {
                "kind": "entity",
                "object_type": "Loan",
                "primary_key": "loan-1",
                "properties": {"status": "PENDING"},
                "version": 1,
            }
        },
        "params": {"status": "APPROVED"},
        "metadata": {},
    }

    runner = BubblewrapRunner()
    result = runner.run_sandboxed_code(implementation_code, "approve", payload)

    assert result["result"] == {"ok": True}
    assert result["edits"].edits[0].properties == {"status": "APPROVED"}


def test_bubblewrap_timeout_error_is_translated(monkeypatch) -> None:
    runner = BubblewrapRunner()
    monkeypatch.setattr(runner, "available", lambda: True)

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="bwrap", timeout=runner._config.timeout_s)

    monkeypatch.setattr(subprocess, "run", _raise_timeout)

    with pytest.raises(SandboxTimeoutError, match="timed out"):
        runner.run_sandboxed_code(
            "def fn(context):\n    return 'ok'",
            "fn",
            payload={"input_instances": {}, "params": {}, "metadata": {}},
        )


def test_bubblewrap_non_zero_exit_becomes_execution_error(monkeypatch) -> None:
    runner = BubblewrapRunner()
    monkeypatch.setattr(runner, "available", lambda: True)

    def _return_failure(*args, **kwargs):
        return subprocess.CompletedProcess(args=["bwrap"], returncode=1, stdout=b"", stderr=b"boom")

    monkeypatch.setattr(subprocess, "run", _return_failure)

    with pytest.raises(SandboxExecutionError, match="boom"):
        runner.run_sandboxed_code(
            "def fn(context):\n    return 'ok'",
            "fn",
            payload={"input_instances": {}, "params": {}, "metadata": {}},
        )
