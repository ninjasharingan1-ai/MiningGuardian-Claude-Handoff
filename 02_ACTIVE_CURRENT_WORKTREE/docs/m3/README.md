# MiningGuardian M3 — Documentation Authority Guide

**Path:** `docs/m3/`  
**Purpose:** Define the authoritative M3 documentation set, source-of-truth hierarchy, review/audit boundaries, and agent usage rules.

---

## 1. Current M3 status

```text
M3.0 Knowledge / Architecture Foundation: FROZEN
Accepted baseline: v0.4.1
Architecture Review #4 Closure Recheck: PASS
Critical blockers: 0
High blockers: 0
Next engineering phase: M3.1 Runtime Observability
```

M3.0 is no longer a draft architecture phase.

Do not redesign, reinterpret, or silently replace frozen M3.0 semantics during M3.1 implementation.

---

## 2. Authoritative source-of-truth hierarchy

When documents disagree, resolve conflicts in this order:

```text
1. Frozen MiningGuardian M2 implementation
2. M2_FINAL_ACCEPTANCE.md
3. M2_FINAL_BASELINE.md
4. M3.0_FINAL_ACCEPTANCE.md
5. M3.0_FINAL_BASELINE.md
6. M3.0_FINAL_FREEZE_MANIFEST.md
7. Accepted M3 canonical documents in docs/m3/
8. Explicit accepted M3 ADRs/specifications compatible with the frozen baseline
9. Review reports in docs/m3/reviews/ as audit evidence only
10. Historical drafts, remediation files, research notes, and archived versions
```

Lower-authority material must never silently override higher-authority material.

---

## 3. Canonical M3.0 documents

The following files are the active canonical M3.0 architecture set:

```text
docs/m3/M3_ARCHITECTURE.md
docs/m3/M3_GLOSSARY.md
docs/m3/M3_DATA_CONTRACTS.md
docs/m3/M3_CONTROL_SAFETY.md
docs/m3/M3_EVALUATION_PROTOCOL.md
docs/m3/M3_RUNTIME_EVIDENCE.md
docs/m3/M3_AGENT_RULES.md
```

These files are the exact accepted v0.4.1 canonical bytes recorded by `M3.0_FINAL_BASELINE.md`.

They are authoritative for M3.0 semantics.

Do not create competing active variants such as:

```text
M3_ARCHITECTURE_v0.2.md
M3_ARCHITECTURE_v0.3.md
M3_ARCHITECTURE_v0.4.md
```

inside the active `docs/m3/` directory.

Historical versions belong outside the active canonical tree.

---

## 4. Final freeze artifacts

Keep these files in the active M3 documentation root:

```text
docs/m3/M3.0_FINAL_ACCEPTANCE.md
docs/m3/M3.0_FINAL_BASELINE.md
docs/m3/M3.0_FINAL_FREEZE_MANIFEST.md
```

Their roles are:

### `M3.0_FINAL_ACCEPTANCE.md`

Records the final M3.0 acceptance decision and frozen architectural boundaries.

### `M3.0_FINAL_BASELINE.md`

Defines the exact accepted baseline, hashes, invariants, ownership boundaries, and implementation constraints.

### `M3.0_FINAL_FREEZE_MANIFEST.md`

Provides integrity references for the frozen artifact set.

Before changing a frozen M3.0 contract, require an explicit accepted superseding ADR or a formally approved new baseline.

---

## 5. Review files are audit evidence only

Store architecture reviews under:

```text
docs/m3/reviews/
```

Recommended retained review set:

```text
M3.0_ARCHITECTURE_REVIEW_1_READ_ONLY_v0.1.md
M3.0_ARCHITECTURE_REVIEW_2_READ_ONLY_v0.2.md
M3.0_ARCHITECTURE_REVIEW_3_READ_ONLY_FREEZE_AUDIT_v0.3.md
M3.0_ARCHITECTURE_REVIEW_4_READ_ONLY_CONTRACT_FREEZE_AUDIT_v0.4.md
M3.0_ARCHITECTURE_REVIEW_4_CLOSURE_RECHECK_PASS_v0.4.1.md
```

Review documents explain:

```text
what failed
why it failed
what was remediated
what was verified
how the final freeze was reached
```

Review documents are **not normative architecture contracts**.

A historical review may contain:

```text
obsolete terminology
rejected semantics
already-remediated findings
temporary ownership models
superseded contract shapes
```

If a review report conflicts with the final canonical M3.0 documents, the final canonical documents and Final Baseline win.

---

## 6. Historical drafts and remediation artifacts

Do not keep obsolete architecture drafts in the active canonical folder.

Recommended external archive:

```text
C:\MiningGuardian_Artifacts\M3.0\history\
```

Example:

```text
history/
├─ v0.1/
├─ v0.2/
├─ v0.3/
├─ v0.4/
└─ v0.4.1-pre-freeze/
```

Recommended final archive:

```text
C:\MiningGuardian_Artifacts\M3.0\final\
```

Containing:

```text
M3.0_FINAL_FREEZE.zip
M3.0_FINAL_FREEZE.sha256
```

Historical artifacts remain valuable for audit and reconstruction of engineering decisions, but they must not be treated as active architecture.

---

## 7. Frozen M2 boundaries remain authoritative

M3 does not silently rewrite M2.

The following M2 boundaries remain frozen unless explicitly superseded:

```text
Evidence → Claim → Hypothesis → Candidate

M2 Policy owns admissibility

Prediction owns future estimate

DUS =
(Benefit × Confidence)
- (Risk + ActionCost + Uncertainty)

DecisionScorer owns scoring
DecisionRanker owns ranking

Prediction ≠ Outcome

Decision ≠ Action
Action ≠ Execution
Execution ≠ Outcome
Outcome ≠ Reward

M2 persistence records/restores
M2 persistence does not re-decide

M2 has no live execution authority
```

---

## 8. Frozen M3.0 semantic boundaries

Agents must preserve these distinctions:

```text
RewardTargetAuthority ≠ M2 Policy

RewardTargetAuthority ≠ RewardTargetController

RewardTarget lifecycle
≠
RewardTargetControllerState

RewardTargetControllerState
≠
RewardTargetAssessment

Assessment Quality
≠
Performance State

Performance State
≠
Attainability

Reward
≠
ADR-0006 Risk / predicted ActionCost / Uncertainty

M2 Policy
≠
Execution Safety Gate

ExecutionAuthorization
≠
ExecutionRecord

LearningArtifact
≠
Active Production Update

M2 DecisionEvaluationRepository
≠
M3 Runtime Evidence Persistence

LLM reasoning
≠
control authority
```

---

## 9. RewardTarget semantics

Accepted RewardTarget objective types:

```text
MINIMUM
BAND
```

`MAXIMIZE` is a strategic optimization objective and is not a RewardTarget setpoint type.

Frozen signed-target-gap convention:

```text
positive = unmet shortfall
zero     = acceptable target region
negative = above acceptable target region
```

No implementation agent may silently reinterpret this convention.

---

## 10. Runtime safety rule

M3.0 does not authorize live autonomous execution.

Future execution must pass accepted deterministic boundaries such as:

```text
DecisionResult
→ ActionRequest
→ ExecutionAuthorization
→ Execution Adapter
→ ExecutionRecord
→ Outcome
```

No AI/LLM may directly:

```text
change GPU clocks/voltage/power/fan
restart the miner
switch pool/algorithm
override safety gates
mutate production state outside accepted contracts
```

---

## 11. Persistence rule

Keep this separation explicit:

```text
M2 DecisionEvaluationRepository
    = frozen M2 decision artifact persistence

M3 Runtime Evidence Persistence
    = durable M3 runtime/evaluation evidence boundary
```

M3 persistence must preserve authoritative facts, identities, timestamps, provenance, versions, and historical evidence.

Persistence must never re-run decision, reward, learning, or promotion logic during reconstruction.

---

## 12. Rules for Codex and implementation agents

Before editing M3 code:

```text
1. Read M3.0_FINAL_ACCEPTANCE.md
2. Read M3.0_FINAL_BASELINE.md
3. Read the relevant canonical M3 documents
4. Inspect existing M2 contracts/tests
5. Identify exact ownership
6. State invariants
7. Implement only the accepted phase scope
8. Add deterministic tests
9. Run local quality gates
10. Request read-only verification
```

Do not:

```text
redesign frozen M3.0 architecture
invent missing semantics when the contract is explicit
revive historical terminology from review files
read historical drafts as current source of truth
merge owners for convenience
silently change frozen M2 contracts
silently alter RewardTarget mathematics
create direct Learning → production mutation
create direct LLM → actuator control
```

If implementation appears to require changing a frozen contract:

```text
STOP
→ document the conflict
→ propose an ADR / architecture change
→ do not silently patch around it
```

---

## 13. Current phase boundary

The next authorized engineering phase is:

```text
M3.1 — Runtime Observability hardening and canonical telemetry contracts
```

M3.1 implementation must not expand into later-phase responsibilities unless explicitly authorized.

Later planned areas include:

```text
M3.2  State Estimation + Economic / Blockchain Intelligence
M3.3  Prediction / Uncertainty / Calibration
M3.4  Outcome + RewardContract + RewardEvaluationWindow
M3.5  Reward Target Authority + Controller — Shadow
M3.6  Learning + Replay / Backtesting + Promotion Gate
M3.7  Safe Control + ExecutionAuthorization + Adapters — Simulation/Shadow
M3.8  Bounded controlled execution
M3.9  Reward-target closed-loop optimization
```

Phase numbering may be refined later, but frozen semantic boundaries may not be silently changed.

---

## 14. Short rule

For any agent entering `docs/m3/`:

```text
FINAL ACCEPTANCE + FINAL BASELINE
        ↓
Canonical M3 documents
        ↓
Accepted ADRs / phase specs
        ↓
Reviews as audit evidence
        ↓
Historical drafts only as history
```

**Current accepted truth wins. Historical context explains it but does not override it.**
