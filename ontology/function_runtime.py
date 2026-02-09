from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .runtime import ActionRunner
from .sandbox import BubblewrapRunner
from .edits import ObjectInstance


class FunctionRuntime:
    def __init__(
        self,
        action_runner: Optional[ActionRunner] = None,
        sandbox_runner: Optional[BubblewrapRunner] = None,
    ) -> None:
        self._action_runner = action_runner or ActionRunner()
        self._sandbox_runner = sandbox_runner or BubblewrapRunner()

    def execute_in_process(
        self,
        fn: Callable[..., Any],
        input_instances: Dict[str, ObjectInstance],
        params: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self._action_runner.execute(fn, input_instances, params=params, metadata=metadata)

    def execute_in_sandbox(self, module_path: str, function_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._sandbox_runner.run(module_path, function_name, payload)
