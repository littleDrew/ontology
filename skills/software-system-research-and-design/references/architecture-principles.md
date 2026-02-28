# Architecture Principles (adapted for software-system-research-and-design)

This reference consolidates architecture-development guidance inspired by the provided software-architecture skill and aligns it with system-level方案设计。

## 1) Library-first / Service-first decision policy
Before designing custom modules, evaluate proven libraries or managed services.

Use this sequence:
1. Define capability requirement (e.g., retry, auth, queue, search).
2. Identify mature options (open-source or SaaS/managed).
3. Compare fit: reliability, security, lock-in, cost, team familiarity.
4. Decide build-vs-buy with explicit rationale.

Build custom implementation only when:
- Business logic is domain-unique.
- Performance constraints require specialized behavior.
- Security/compliance demands full control.
- Existing options fail core requirements.

## 2) Clean Architecture + DDD guardrails
- Separate domain logic from infrastructure and delivery layers.
- Keep business rules framework-agnostic.
- Define bounded contexts and ownership boundaries.
- Avoid cross-context leakage via ad-hoc shared modules.

Expected artifacts:
- Context map
- Domain model outline
- Use-case/service boundaries

## 3) Naming and modularity standards
- Prefer domain-specific names (`OrderScoringService`, `RiskPolicyEvaluator`).
- Avoid vague buckets (`utils`, `helpers`, `common`) for mixed responsibilities.
- Keep modules single-purpose with clear ownership.

## 4) Maintainability heuristics for proposed implementation
- Prefer early-return and shallow control flow in code-level recommendations.
- Decompose large components/functions into smaller units.
- Keep responsibilities explicit at module boundaries.
- Require error-handling strategy for each critical integration.

## 5) Anti-pattern checklist (must report in final output)
Mark each as pass/fail:
- Jumping to tech stack without requirement clarity
- Single方案输出 without alternatives
- No explicit failure/degradation/rollback path
- Qualitative scalability discussion without rough numbers
- Mixing domain logic and infrastructure concerns
- Unjustified custom implementation where proven options exist

If any fail, add remediation actions in the final recommendation.
