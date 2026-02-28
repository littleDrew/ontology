# Installation and Execution Evaluation Guide

## 1) Installation methods

### Method A (Recommended): install from GitHub URL via skill-installer
Use Codex `skill-installer` to install directly from repository source path.

```bash
$skill-installer install https://github.com/<org>/<repo>/tree/<branch>/skills/software-system-research-and-design
```

Notes:
- Replace `<org>/<repo>/<branch>` with your real repository coordinates.
- After install, restart Codex to load new skills.

### Method B (CLI script fallback): install from GitHub URL
If your environment exposes the installer script directly:

```bash
python3 /opt/codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --url https://github.com/<org>/<repo>/tree/<branch>/skills/software-system-research-and-design
```

### Method C (Optional): local package generation
Only use when your environment explicitly requires packaged `.skill` files.

The output directory can be any temporary local path (for example `/tmp/codex-skill-dist`).

```bash
python3 /opt/codex/skills/.system/skill-creator/scripts/package_skill.py \
  skills/software-system-research-and-design \
  /tmp/codex-skill-dist
```

Repository policy recommendation:
- Do not commit `.skill` binary artifacts; keep source files as truth.

---

## 2) Post-install checklist

### Source integrity checks
- Skill folder contains `SKILL.md`.
- `references/` contains:
  - `architecture-principles.md`
  - `research-map.md`
  - `method-playbook.md`
  - `installation-and-evaluation.md`
  - `reference.md`

### Runtime checks
- Start a fresh Codex session.
- Issue one trigger prompt and one non-trigger prompt.
- Verify the skill triggers only for relevant architecture-design tasks.

---

## 3) Smoke test prompts

### Trigger test A (should trigger)
"请先调研再分析，设计一个支持百万DAU的即时通信系统，给出候选架构和trade-off。"

Expected behavior:
- Collect constraints/assumptions first.
- Provide at least 2 architecture candidates.
- Include quantitative estimation and trade-off matrix.

### Trigger test B (should trigger)
"帮我做电商订单系统架构选型，要求高可用、可扩展，并给出落地路线图。"

Expected behavior:
- Discuss consistency/availability/capacity constraints.
- Include build-vs-buy decisions.
- Provide migration and rollback planning.

### Non-trigger test (should NOT strongly trigger)
"把这段Python代码修成可运行。"

Expected behavior:
- Prefer coding/debugging behavior, not system-design long-form workflow.

---

## 4) Execution quality rubric (score 0-2 each)

1. **Requirement clarity**: captures use cases, constraints, and assumptions.
2. **Research grounding**: cites relevant source material and evidence links.
3. **Alternative depth**: includes >=2 viable architecture options.
4. **Derivation depth**: covers data/API/consistency/scaling/reliability/security.
5. **Quantitative rigor**: includes rough capacity/latency/storage estimates.
6. **Decision quality**: weighted trade-off matrix and explicit rejection reasons.
7. **Implementation readiness**: milestone plan, validation strategy, rollback plan.
8. **Anti-pattern control**: explicit pass/fail checks with remediation.

Interpretation:
- 13-16: Excellent (production planning ready)
- 9-12: Acceptable (needs targeted refinement)
- <=8: Rework needed (process not followed)

---

## 5) Common failure modes and fixes
- **Failure: Jumps directly to one architecture.**
  - Fix: enforce Step 1 + Step 3 minimum outputs.
- **Failure: No numbers, only qualitative claims.**
  - Fix: require at least one storage and one throughput estimate.
- **Failure: Missing rollback or observability.**
  - Fix: block final recommendation until Step 6 is complete.
- **Failure: Over-customized implementation.**
  - Fix: run build-vs-buy checklist from `architecture-principles.md`.

---

## 6) Capability coverage checklist
Mark each item as Yes/No during acceptance:
- Detailed requirement confirmation includes: domain, scenario, competitor, competitor docs, workload type, data volume/concurrency, reliability targets.
- Research framework includes: competitor, open-source options, technology stack, constraints mapping.
- Analysis template includes: goals, assumptions, trade-offs, risks (+ mitigation).
- Deliverable includes implementable design doc: architecture explanation, module split, concrete implementation plan, test/acceptance criteria.
- Reference digest exists with links and valuable notes (`references/reference.md`).
