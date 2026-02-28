# Method Playbook: 调研 -> 分析推导 -> 可行方案

## A. Standard execution protocol

### Phase 1: 调研（需求确认 + 外部调研）
- Confirm problem framing with mandatory fields:
  - Domain
  - Core scenario
  - Competitors and competitor documents
  - Workload class (commercial/internal), target volume/concurrency
  - Reliability targets (SLA/RTO/RPO)
- Build source-backed knowledge snapshot.
- Identify unknowns and explicitly track assumptions.

Deliverable:
- Requirement confirmation record
- Requirement table (functional/non-functional)
- Assumption list
- Research digest with evidence links

### Phase 2: 分析与推导
- Generate 2-3 architecture candidates.
- Derive details by goals -> assumptions -> design choices -> trade-offs -> risks.
- Validate with rough calculations and bottleneck reasoning.

Deliverable:
- Candidate diagrams
- Derivation table (goal/assumption/trade-off/risk)
- Data/API/storage/concurrency design notes
- Capacity estimates
- Risk and bottleneck map

### Phase 3: 可行实现方案
- Select architecture using weighted trade-off matrix.
- Break down into implementation roadmap.
- Define test and acceptance standards.
- Define observability, migration, and rollback.

Deliverable:
- Final recommendation
- Architecture doc (diagram + module split + implementation details)
- Milestone plan
- Test & acceptance criteria
- Risk mitigation and open questions

---

## B. Analysis and derivation template

| Goal | Assumption | Design Choice | Trade-off | Risk | Mitigation |
|---|---|---|---|---|---|
| Example: p99 < 200ms | cache hit rate > 85% | cache-aside + Redis cluster | more ops complexity | cache inconsistency | versioning + TTL + fallback |

Usage rule:
- Fill this table for each candidate architecture.
- Avoid skipping assumptions; if unknown, mark explicit validation plan.

---

## C. Trade-off matrix template

| Criterion | Weight | Option A | Option B | Option C | Notes |
|---|---:|---:|---:|---:|---|
| Performance | 0.20 |  |  |  | |
| Scalability | 0.20 |  |  |  | |
| Availability/Resilience | 0.15 |  |  |  | |
| Consistency/Correctness | 0.15 |  |  |  | |
| Delivery speed | 0.10 |  |  |  | |
| Dev complexity | 0.10 |  |  |  | |
| Ops complexity | 0.05 |  |  |  | |
| Cost | 0.05 |  |  |  | |

Scoring rule:
- Score each criterion 1-5.
- Final score = sum(weight * score).
- Reject “highest score wins blindly”; include risk-adjusted judgment.

---

## D. Prompt snippets for Codex use

### 1) 需求澄清提示词
"先不要给方案，先确认：领域、核心场景、是否有竞品、竞品是否有公开架构文档、是否商用及目标数据量/并发量、可靠性目标(SLA/RTO/RPO)、合规约束。缺失信息用假设A1..An标记。"

### 2) 调研框架提示词
"基于当前约束，按‘竞品、开源方案、技术栈、约束’四栏输出调研框架，并给出资料链接与价值摘要。"

### 3) 深度推导提示词
"对候选架构逐一按‘目标->假设->设计选择->权衡->风险->缓解措施’推导，并补充容量估算。"

### 4) 决策与落地提示词
"给出带权重的trade-off矩阵并推荐最终方案；输出架构图说明、模块拆分、具体实现、测试验收标准、迁移与回滚计划。"

---

## E. Anti-pattern checklist
- Directly jump to technology selection without clear requirements.
- Provide a single architecture without alternatives.
- Ignore failure mode, rollback, and observability.
- Discuss scalability qualitatively without any numbers.
- Claim “best practice” without contextual trade-offs.
