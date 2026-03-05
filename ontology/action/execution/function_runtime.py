from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .runtime import ActionRunner
from .sandbox import BubblewrapRunner
from ..storage.edits import ObjectInstance, RelationInstance


class FunctionRuntime:
    """Higher-level runtime adapter for local or sandbox function execution."""
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
        input_instances: Dict[str, Any],
        params: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self._action_runner.execute(fn, input_instances, params=params, metadata=metadata)

    def execute_in_sandbox(
        self,
        implementation_code: str,
        function_name: str,
        input_instances: Dict[str, ObjectInstance],
        params: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        serialized_inputs: Dict[str, Any] = {}
        for name, instance in input_instances.items():
            if isinstance(instance, ObjectInstance):
                serialized_inputs[name] = {
                    "kind": "entity",
                    "object_type": instance.object_type,
                    "primary_key": instance.primary_key,
                    "properties": dict(instance.properties),
                    "version": instance.version,
                }
                continue
            if isinstance(instance, RelationInstance):
                serialized_inputs[name] = {
                    "kind": "relation",
                    "link_type": instance.link_type,
                    "from": {
                        "object_type": instance.from_locator.object_type,
                        "primary_key": instance.from_locator.primary_key,
                        "version": instance.from_locator.version,
                    },
                    "to": {
                        "object_type": instance.to_locator.object_type,
                        "primary_key": instance.to_locator.primary_key,
                        "version": instance.to_locator.version,
                    },
                }
                continue
            raise ValueError(f"Unsupported input instance type for sandbox serialization: {type(instance)}")

        payload = {
            "input_instances": serialized_inputs,
            "params": params or {},
            "metadata": metadata or {},
        }
        return self._sandbox_runner.run_sandboxed_code(implementation_code, function_name, payload)
