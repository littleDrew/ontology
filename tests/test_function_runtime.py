import pytest

from ontology import FunctionRuntime
from ontology.edits import ObjectInstance, ObjectLocator
from ontology.runtime import function_action
from ontology.sandbox import BubblewrapRunner


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
    with pytest.raises(RuntimeError):
        runtime.execute_in_sandbox("module", "fn", {"x": 1})
