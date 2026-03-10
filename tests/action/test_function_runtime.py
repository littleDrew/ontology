import pytest

from ontology import FunctionRuntime
from ontology.action.storage.edits import ObjectInstance
from ontology.action.execution.runtime import function_action
from ontology.action.execution.sandbox import BubblewrapRunner
from ontology.action.storage.edits import TransactionEdit


@function_action
def approve(loan: ObjectInstance, context) -> str:
    loan.status = "APPROVED"
    return "ok"


def test_function_runtime_in_process() -> None:
    runtime = FunctionRuntime()
    loan = ObjectInstance("Loan", "loan-5", {"status": "PENDING"}, version=1)
    result = runtime.execute_in_process(approve, {"loan": loan})
    edits = result["edits"]
    assert edits.edits[0].properties["status"] == "APPROVED"


def test_function_runtime_sandbox_unavailable() -> None:
    runner = BubblewrapRunner()
    if runner.available():
        pytest.skip("bubblewrap available; sandbox runtime test not needed")
    runtime = FunctionRuntime(sandbox_runner=runner)
    loan = ObjectInstance("Loan", "loan-5", {"status": "PENDING"}, version=1)
    with pytest.raises(RuntimeError):
        runtime.execute_in_sandbox(
            "def fn(context):\n    return 'ok'",
            "fn",
            {"loan": loan},
        )


def test_function_runtime_exposes_in_sandbox_api() -> None:
    runtime = FunctionRuntime()
    assert hasattr(runtime, "execute_in_sandbox")
    assert not hasattr(runtime, "execute_sandboxed")


def test_function_runtime_sandbox_payload_shape() -> None:
    class StubRunner:
        def run_sandboxed_code(self, implementation_code, function_name, payload):
            assert implementation_code.startswith("def fn")
            assert function_name == "fn"
            assert payload["input_instances"]["loan"]["object_type"] == "Loan"
            assert payload["params"] == {"status": "APPROVED"}
            return {"result": "ok", "edits": TransactionEdit(edits=[])}

    runtime = FunctionRuntime(sandbox_runner=StubRunner())
    loan = ObjectInstance("Loan", "loan-5", {"status": "PENDING"}, version=1)
    result = runtime.execute_in_sandbox(
        "def fn(loan, context, status):\n    return 'ok'",
        "fn",
        {"loan": loan},
        params={"status": "APPROVED"},
    )
    assert result["result"] == "ok"
