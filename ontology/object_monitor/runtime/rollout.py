from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence


@dataclass(frozen=True)
class RolloutMetrics:
    evaluation_latency_ms: Sequence[int]
    action_total: int
    action_success_after_retry: int
    dlq_count: int


@dataclass(frozen=True)
class RolloutGateConfig:
    evaluation_latency_p95_ms_threshold: int = 3000
    action_success_rate_threshold: float = 0.99
    dlq_ratio_threshold: float = 0.001


@dataclass(frozen=True)
class RolloutGateResult:
    passed: bool
    evaluation_latency_p95_ms: int
    action_success_rate: float
    dlq_ratio: float
    failed_reasons: List[str]


@dataclass(frozen=True)
class RolloutDecision:
    current_percent: int
    next_percent: int
    should_rollback: bool
    reason: str


class RolloutGateEvaluator:
    """W7-W8 灰度门禁评估器：按验收阈值评估是否可推进流量。"""

    def __init__(self, config: RolloutGateConfig | None = None) -> None:
        self._config = config or RolloutGateConfig()

    def evaluate(self, metrics: RolloutMetrics) -> RolloutGateResult:
        p95 = _percentile(metrics.evaluation_latency_ms, 95)
        success_rate = (metrics.action_success_after_retry / metrics.action_total) if metrics.action_total else 0.0
        dlq_ratio = (metrics.dlq_count / metrics.action_total) if metrics.action_total else 1.0

        reasons: List[str] = []
        if p95 >= self._config.evaluation_latency_p95_ms_threshold:
            reasons.append("evaluation_latency_p95_exceeded")
        if success_rate < self._config.action_success_rate_threshold:
            reasons.append("action_success_rate_too_low")
        if dlq_ratio >= self._config.dlq_ratio_threshold:
            reasons.append("dlq_ratio_too_high")

        return RolloutGateResult(
            passed=not reasons,
            evaluation_latency_p95_ms=p95,
            action_success_rate=success_rate,
            dlq_ratio=dlq_ratio,
            failed_reasons=reasons,
        )

    def decide(self, *, current_percent: int, gate_result: RolloutGateResult) -> RolloutDecision:
        ladder = [5, 20, 50, 100]
        if not gate_result.passed:
            return RolloutDecision(
                current_percent=current_percent,
                next_percent=current_percent,
                should_rollback=True,
                reason=",".join(gate_result.failed_reasons) or "gate_failed",
            )

        next_percent = current_percent
        for value in ladder:
            if value > current_percent:
                next_percent = value
                break

        return RolloutDecision(
            current_percent=current_percent,
            next_percent=next_percent,
            should_rollback=False,
            reason="gate_passed",
        )


def _percentile(values: Sequence[int], p: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, int((p / 100) * len(ordered)) - 1))
    return ordered[rank]
