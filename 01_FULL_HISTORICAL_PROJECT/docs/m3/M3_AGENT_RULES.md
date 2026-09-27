# M3 Agent Rules

## Authority and status

**Status:** M3.0 Foundation Draft v0.4.1 — freeze cleanup; architecture/knowledge only; no runtime execution authority is created by this document.

Resolve conflicts in this order:

1. Frozen MiningGuardian M2 implementation.
2. `M2_FINAL_ACCEPTANCE.md`.
3. `M2_FINAL_BASELINE.md`.
4. `M3_ENGINEERING_HANDOFF.md`.
5. Explicit accepted M3 ADRs/specifications compatible with the frozen M2 baseline.
6. Accepted M3 canonical knowledge documents in `docs/m3/`.
7. Historical drafts and research notes as context only.

M3 must not silently rewrite frozen M2 semantics. Any intentional semantic replacement requires an explicit superseding ADR.


> v0.4.1 preserves v0.4 architecture and performs only Review #4 freeze-cleanup corrections: ownership wording, controller/assessment invariants, stale terminology, final-gate reference, glossary de-duplication, and introductory evidence-chain alignment.


## 1. Purpose

Define how human and AI engineering roles collaborate without blurring architecture, implementation, verification, and runtime authority.

## 2. Project roles

### Human owner

Owns final acceptance, risk tolerance, execution scope, and irreversible/high-risk approvals.

### ChatGPT / Architecture work

Owns architecture synthesis, contract design, semantic review, ADR drafting, cross-layer reasoning, and orchestration of the M3 knowledge foundation.

### Codex / implementation agent

Implements accepted architecture with minimal semantic invention.

It must inspect current contracts/tests before editing and must not silently redesign ownership.

### Independent verifier / Antigravity-style verifier

First verification pass is read-only.

It reports findings before any remediation is authorized.

### Wolfram / mathematical oracle

Used for independent mathematical verification where useful.

It is not project ground truth.

### Runtime LLM strategic reasoning

Future in-system layer only.

It is advisory and cannot actuate directly.

## 3. M3 engineering skills

The five current expert lenses are:

```text
M3 Cognitive Systems Architect
M3 Time-Series & Statistical Learning Engineer
M3 Safe Control & Optimization Engineer
M3 Experimental Verification Engineer
M3 Runtime Observability Engineer
```

They are not competing agents and do not own duplicated authority.

## 4. Cross-skill responsibility

### Cognitive Architect
Architecture, ontology, ownership, interfaces, ADRs.

### Time-Series / Statistical Learning
Temporal semantics, state estimation, forecasting, uncertainty, calibration, drift, ML validation.

### Safe Control / Optimization
Control semantics, safety envelope, execution gating, rollback, anti-churn, action-cost-aware optimization.

### Experimental Verification
Independent tests, mathematical verification, simulation, replay, fault injection, evidence acceptance.

### Runtime Observability
Telemetry contracts, timestamps, freshness, data quality, correlation, runtime evidence.

## 5. Reward Target Control Loop ownership

Reward-target work is mandatory and cross-cutting.

### Reward Target Authority
Owns target creation, change, retirement, versioning, objective type, units, and Reward Contract binding.

### Reward Target Controller
Consumes an authorized ACTIVE target and owns controller availability/state plus orchestration of RewardTargetAssessment and reevaluation triggers. Lifecycle, assessment quality, performance state, signed gap, and attainability remain distinct semantics.

### Decision Engine
Remains owner of decision orchestration through frozen M2 contracts.

### Safe Control
Owns future safety/execution path.

### Outcome/Reward subsystem
Owns mature observed Outcome and Reward evaluation.

### Learning subsystem
Owns evidence-backed `LearningArtifact` and `UpdateProposal` creation after mature Outcome.

### Promotion boundary
Owns the explicit verified decision to activate/reject a proposed model/knowledge update.

No direct `LearningArtifact → Active Version` path is allowed.

No skill may collapse these owners into one convenience module without an accepted ADR.

## 6. Architectural gaps register

The phrase **"architectural gaps" / "فراغات معمارية"** refers to this mandatory register:

1. Outcome / Reward / Learning ownership and contracts.
2. Reward Target Control Loop as a first-class core subsystem, with separate target lifecycle, controller state, assessment quality, performance state, signed gap, and attainability.
3. Runtime Strategic Reasoning layer with no direct control authority.
4. Economic / Blockchain Intelligence layer, required before meaningful Reward Target shadow evaluation.
5. Reward Contract + Reward Evaluation Window / Pool Time Block semantics.
6. Execution Adapters, ExecutionAuthorization, and capability discovery.
7. Cross-layer ownership boundaries among Observability, Statistical Learning, Decision, Reward Target Authority, Target Control, Safe Control, Outcome/Reward/Learning, Promotion, and Verification.
8. M3.0 canonical knowledge documents.
9. Staged path from shadow/replay to bounded execution and autonomous optimization.
10. M3 Runtime Evidence Persistence ownership, separate from frozen M2 persistence.
11. ACTION_ATTRIBUTED baseline/reference requirements before learning/promotion.

These items must not disappear from future planning.

## 7. Semantic non-negotiables

```text
Telemetry ≠ Estimated State
Estimated State ≠ Prediction
Prediction ≠ Outcome
Outcome ≠ Reward
Reward Target Authority ≠ M2 Policy
Reward Target Authority ≠ Target Controller
Reward Target Lifecycle ≠ Reward Target Controller State
Reward Target Controller State ≠ Reward Target Assessment
Assessment Quality ≠ Performance State
Performance State ≠ Attainability
Target ≠ Decision
Decision ≠ Action
Action ≠ Execution
M2 Policy ≠ Execution Safety Gate
Learning Artifact ≠ Active Production Update
LLM reasoning ≠ control authority
```

## 8. Source hierarchy rule

Never revive a historical ADR draft when it conflicts with the frozen M2 baseline.

Before changing a frozen contract, require an explicit superseding ADR.

## 9. Implementation rule

Before implementation:

1. inspect authoritative docs/contracts;
2. identify exact ownership;
3. state invariants;
4. identify persistence/observability impact;
5. define tests;
6. implement minimal accepted delta;
7. run local gates;
8. request read-only independent verification.

## 10. Verification rule

First verification pass:

```text
READ ONLY
```

Do not patch while verifying.

Return exact findings and evidence.

## 11. Runtime authority rule

No AI/LLM tool may directly:

- change GPU clocks/voltage/power/fan;
- restart miner;
- switch pool/algorithm;
- mutate wallet;
- override safety gates.

Future execution happens only through accepted Safe Control + Execution Adapter contracts.

## 12. Model rule

Do not choose ML/control algorithms because they are fashionable.

PID, MPC, state-space, contextual bandits, RL, or other methods remain candidates until requirements/evidence justify them.

## 13. Reward rule

Do not optimize raw hashrate as the primary system objective.

Reward targeting must be explicit, unit-aware, Reward-Contract-bound, uncertainty-aware, action-cost-aware, and subordinate to safety/continuity.

Do not duplicate ADR-0006 Risk/ActionCost/Uncertainty penalties inside the reward metric unless an explicit superseding ADR changes the scoring contract.

`MAXIMIZE` is a strategic optimization objective, not a RewardTarget objective type. Runtime RewardTarget uses explicit `MINIMUM` or `BAND` semantics.

`signed_target_gap` follows the frozen sign convention: positive shortfall, zero acceptable region, negative above acceptable region; it is unavailable when assessment quality is not VALID.

## 14. No-restart-churn rule

MiningGuardian strongly prefers stable long-run operation.

Repeated restarts/switches must be treated as costly and potentially pathological.

## 15. Final M3.0 gate

No M3.1 runtime implementation may begin until all of the following are true:

- the seven canonical documents are reviewed and internally consistent;
- frozen M2 invariants are confirmed;
- Reward Target Authority / Reward Target Controller / Outcome / Reward / Learning / Promotion ownership is accepted;
- Architecture Review #4 contract-freeze audit closure recheck is completed in read-only mode with PASS;
- all `CRITICAL` and `HIGH` freeze blockers are resolved;
- any remaining limitations are explicitly classified as accepted non-blocking limitations;
- `M3.0_FINAL_ACCEPTANCE.md` is created;
- `M3.0_FINAL_BASELINE.md` is created.

A blocker being documented does not make it resolved.
