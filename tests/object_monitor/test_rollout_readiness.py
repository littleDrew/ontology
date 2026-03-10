from ontology.object_monitor.runtime import RolloutGateEvaluator, RolloutMetrics


def test_w7_w8_gate_pass_and_progress_ladder() -> None:
    evaluator = RolloutGateEvaluator()
    metrics = RolloutMetrics(
        evaluation_latency_ms=[100, 120, 140, 150, 180, 200, 220, 250, 300, 450],
        action_total=1000,
        action_success_after_retry=995,
        dlq_count=0,
    )

    result = evaluator.evaluate(metrics)
    decision = evaluator.decide(current_percent=5, gate_result=result)

    assert result.passed is True
    assert result.evaluation_latency_p95_ms < 3000
    assert result.action_success_rate >= 0.99
    assert result.dlq_ratio < 0.001
    assert decision.next_percent == 20
    assert decision.should_rollback is False


def test_w7_w8_gate_fail_and_trigger_rollback() -> None:
    evaluator = RolloutGateEvaluator()
    metrics = RolloutMetrics(
        evaluation_latency_ms=[1000, 2000, 3000, 5000, 8000],
        action_total=1000,
        action_success_after_retry=970,
        dlq_count=5,
    )

    result = evaluator.evaluate(metrics)
    decision = evaluator.decide(current_percent=20, gate_result=result)

    assert result.passed is False
    assert "evaluation_latency_p95_exceeded" in result.failed_reasons
    assert "action_success_rate_too_low" in result.failed_reasons
    assert "dlq_ratio_too_high" in result.failed_reasons
    assert decision.should_rollback is True
    assert decision.next_percent == 20
