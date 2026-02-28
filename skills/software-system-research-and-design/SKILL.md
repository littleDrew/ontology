---
name: software-system-research-and-design
description: Structured research, deep analysis, and implementation-option synthesis for software system architecture and solution design. Use when users ask for system方案设计, 架构选型, trade-off分析, 容量评估, DDD/Clean Architecture对齐, or end-to-end technical方案输出 (especially when requiring “先调研再分析再给可行方案”).
---

# Software System Research and Design

## Overview
Drive architecture work in three explicit phases: **research first**, **reasoning and derivation second**, **feasible implementation proposal third**. Produce auditable decisions with assumptions, alternatives, trade-offs, and rollout path.

## Execution Modes
- **Quick mode (15-30 min)**: one candidate + one fallback, simplified calculations.
- **Standard mode (30-90 min)**: 2-3 candidates + weighted trade-off matrix.
- **Deep mode (90+ min)**: full candidate set, failure-injection plan, migration/rollback details.

Default to **Standard mode** unless user asks for speed.

## Workflow

### Step 0: Establish architecture quality principles
Load `references/architecture-principles.md` and apply these defaults unless user constraints conflict:
- Library-first (buy/integrate before build)
- Clean Architecture + DDD boundaries
- Explicit anti-pattern checks
- Maintainability guardrails (readability, decomposition, ownership clarity)

### Step 1: Clarify scope and constraints (must ask before proposing)
Extract business goal, functional scope, non-functional requirements, and hard constraints before proposing architecture.

Use this checklist (mandatory):
- Domain and business context?
- Primary scenario(s) and user journey?
- Similar competitors/products? Which ones?
- Are there competitor architecture writeups/docs available?
- Is target workload commercial or internal-only?
- Traffic scale (QPS/DAU/peak multiplier)?
- Data volume growth projection (6-24 months)?
- Read/write ratio and latency SLO/SLA?
- Reliability target (SLA, RTO, RPO)?
- Compliance, security, and data locality constraints?
- Delivery constraints (team size, timeline, budget, stack)?

If key info is missing, list assumptions explicitly as `Assumption A1...An`.

### Step 2: Build focused research framework
Use `references/research-map.md` and `references/reference.md` to pick only relevant materials by scenario:
- Competitor analysis (feature scope, architecture clues, cost model)
- Open-source alternatives (maturity, adoption, operability)
- Technology stack options (language/runtime/storage/middleware)
- Constraints mapping (business, technical, org, compliance)

Output a **research digest**:
- `Knowns` (facts)
- `Unknowns` (gaps)
- `Candidate approaches` (2-4 options)
- `Evidence links` (source -> claim)

### Step 3: Create high-level architecture candidates
Produce 2-3 candidate architectures with concise diagrams (ASCII/mermaid text allowed), each including:
- Core components and bounded-context boundaries
- Critical data flow and control flow
- State ownership and consistency model
- Failure domains and degradation behavior

Do not lock to one option yet.

### Step 4: Analyze and derive (goal-assumption-tradeoff-risk template)
For each candidate, perform structured derivation:
1. Goals and success criteria mapping
2. Assumptions and validation method
3. Data model and storage strategy (SQL/NoSQL/cache/search)
4. API and domain boundaries
5. Concurrency and consistency approach
6. Scaling path (LB, sharding, async queues, caching)
7. Reliability mechanisms (timeouts, retries, circuit breaking, idempotency)
8. Security controls (authn/authz, secrets, encryption, audit)
9. Trade-offs and risks (with mitigations)

Use quantitative checks whenever possible:
- Back-of-the-envelope calculations (storage, throughput, bandwidth)
- Capacity headroom and hot-spot risks
- Cost/complexity estimates

### Step 5: Trade-off decision and final recommendation
Use a decision matrix (score 1-5) with weighted criteria:
- Performance
- Scalability
- Availability/resilience
- Consistency correctness
- Implementation complexity
- Operational complexity
- Cost
- Time-to-delivery

Output:
- Recommended architecture
- Why alternatives were rejected
- Key risks and mitigation plan

### Step 6: Produce implementation-ready solution design document
Convert the chosen design into an actionable plan with a document that always includes:
- Architecture diagram explanation
- Module decomposition and ownership boundaries
- Concrete implementation plan (service/storage/middleware/API)
- Milestones (MVP -> scale version)
- Work breakdown by subsystem
- Build-vs-buy integration plan (libraries/services)
- Test and acceptance criteria (functional, performance, reliability)
- Observability plan (SLI/SLO, logs, metrics, tracing, alerts)
- Migration and rollback strategy

## Required Output Contract
Always provide:
1. Context & Goals
2. Requirement Confirmation Record (domain, scenario, competitors, docs, workload class)
3. Requirements & Constraints
4. Assumptions
5. Research Summary (with citations)
6. Candidate Architectures
7. Detailed Derivation (goals, assumptions, trade-offs, risks)
8. Trade-off Matrix & Decision
9. Implementation-ready Design Document
10. Test & Acceptance Standards
11. Risks, Open Questions, Next Actions
12. Anti-Pattern Check Result (pass/fail + remediation)

## Quality Bar
Before finalizing, verify:
- Every major design choice has rationale and trade-off.
- Non-functional requirements map to concrete mechanisms.
- Capacity numbers are internally consistent.
- Failure and rollback paths are explicitly designed.
- Recommendation is executable within stated constraints.
- Build-vs-buy choice is justified for each critical capability.

## Operational Validation
After installing this skill, run the smoke tests in `references/installation-and-evaluation.md` to verify:
- Trigger quality (skill invoked at the right time)
- Process compliance (research -> derivation -> recommendation)
- Outcome quality (actionable plan with risks, metrics, rollback)

## Resources
- Use `references/reference.md` as the primary curated reference digest (links + valuable notes).
- Use `references/installation-and-evaluation.md` for installation checklist, smoke tests, and scoring rubric.
- Use `references/architecture-principles.md` for architecture quality baselines and anti-pattern checks.
- Use `references/research-map.md` for source navigation and scenario matching.
- Use `references/method-playbook.md` for end-to-end analysis playbook and ready-to-use prompts.
