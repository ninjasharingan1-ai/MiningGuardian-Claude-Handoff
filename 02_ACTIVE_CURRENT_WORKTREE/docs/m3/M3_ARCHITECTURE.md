# M3 Architecture

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


## 1. Mission

MiningGuardian evolves from an evidence-driven decision system into a safe autonomous mining cognitive control system:

```text
Observe
→ Understand
→ Estimate State
→ Predict
→ Decide
→ Act Safely
→ Measure Outcome
→ Evaluate Reward
→ Compare Against Target
→ Learn
→ Adapt
```

M3.0 establishes the architecture required for that loop. It does not itself authorize live control.

## 2. Frozen M2 foundation

The accepted M2 pipeline remains:

```text
World State
→ Evidence Foundation
→ Claims / Hypotheses
→ DecisionContext
→ Candidate Generation
→ Policy Validation
→ Prediction
→ ADR-0006 Scoring
→ Ranking
→ Decision Confidence
→ DecisionResult
→ DecisionExplanation
→ Persistence
→ Reconstruction
```

The Decision Utility Score remains:

```text
DUS = (Benefit × Confidence) - (Risk + ActionCost + Uncertainty)
```

Ownership remains frozen unless explicitly superseded:

- Policy owns admissibility.
- Prediction owns future estimates.
- `DecisionScorer` owns ADR-0006 scoring.
- `DecisionRanker` owns rank production.
- Persistence records/restores; it does not re-decide.
- `timestamp_iso` remains authoritative for frozen M2 reconstruction.
- Prediction is not Outcome.
- M2 has no execution authority.

## 3. M3.0 architectural layers

```text
REALITY
  │
  ▼
Runtime Observability
  │
  ├──────────────► Evidence / Cognitive Foundation
  │
  ▼
Derived Metrics / Estimated State
  │
  ├──────────────► Economic / Blockchain State
  │
  └──────────────► Prediction / Uncertainty
                        │
RewardTargetAuthority   │
  │                     │
  ▼                     │
Versioned RewardTarget  │
  │                     │
  ▼                     │
RewardTargetController ◄┘
  │
  ▼
RewardTargetControllerState + RewardTargetAssessment
  │
  ▼
DecisionContext / Decision Evaluation
  │
  ▼
M2 Decision Engine
  │
  ▼
Safe Control / ExecutionAuthorization
  │
  ▼
Execution Adapter
  │
  ▼
Plant / Miner / GPU / Pool
  │
  ▼
Runtime Observability
  │
  ▼
Outcome → Reward Evaluation → Target Comparison
  │
  ▼
LearningArtifact → UpdateProposal → Verification → PromotionDecision
  │
  └──────────────► future state / prediction / strategy
```

`Runtime Strategic Reasoning` may advise Evidence/Strategy/Target-Authority processes but never directly actuates.


`Experimental Verification` is cross-cutting across every layer.

## 3.1 Target authority separation

Reward target definition is governed independently from reward target tracking.

```text
Human / accepted strategy / Target Authority
→ RewardTargetAuthority
→ versioned RewardTarget
→ RewardTargetController
```

This separation prevents the runtime controller from redefining success criteria in response to poor attainment.

## 4. First-class M3 architectural requirement: Reward Target Control Loop

Reward-target control is a core system capability, equal in architectural importance to observation, prediction, decision, and safe control.

The target loop is:

```text
Economic Reward Target
→ Current Reward State
→ Target Gap
→ Target Attainability
→ Decision Evaluation Trigger
→ M2 Candidate / Policy / Prediction / DUS / Ranking
→ Selected Decision
→ Safe Action Authorization
→ Execution
→ Outcome Observation
→ Realized Reward
→ Target Comparison
→ Learning / Hold / Adapt / Rollback
↺
```

The controller MUST NOT directly bypass M2 decision ownership.

### Reward Target Authority owns target definition

A separate `RewardTargetAuthority` owns:

- creating a target;
- changing or retiring a target;
- target identity/version;
- target metric and economic basis;
- target objective type (`MINIMUM` or `BAND`);
- target value/band;
- effective/expiry semantics;
- approved accounting unit;
- allowed source/strategy for target creation.

Target changes must be versioned and auditable.

The active Reward Target Controller must not move its own goalposts.

### Reward Target Controller owns target-tracking orchestration

The Reward Target Controller owns:

- consuming one active, externally authorized Reward Target;
- `controller_status`;
- selecting/initiating an evaluation window under the target contract;
- orchestrating creation/refresh of `RewardTargetAssessment`;
- consuming assessment results for control-loop orchestration;
- target urgency / reevaluation-trigger orchestration subject to safety;
- triggering/recommending a new Decision evaluation when warranted.

The Reward Target Controller does **not** semantically own:

- `assessment_quality`;
- `current_reward_state`;
- `performance_state`;
- `signed_target_gap`;
- `attainability`;
- `attainability_reason`.

Those belong to `RewardTargetAssessment`.

### Reward Target Controller does not own

- target creation/change/retirement;
- candidate generation;
- policy admissibility;
- ADR-0006 scoring;
- candidate ranking;
- direct actuation;
- Outcome fabrication;
- Reward calculation from predicted values;
- model retraining.

### Target lifecycle, controller state, assessment quality, performance state, and attainability

v0.4 explicitly separates five concepts that must not share one enum.

#### RewardTarget lifecycle

```text
DRAFT
ACTIVE
EXPIRED
RETIRED
SUPERSEDED
```

Only an `ACTIVE` target may be consumed for target tracking.

#### RewardTargetControllerState

```text
NO_ACTIVE_TARGET
ACTIVE
ASSESSMENT_UNAVAILABLE
```

This describes controller availability, not reward performance.

#### RewardTargetAssessment.performance_state

When and only when `assessment_quality = VALID`:

```text
BELOW_TARGET
WITHIN_TARGET_BAND
ABOVE_TARGET
```

#### RewardTargetAssessment.assessment_quality

```text
VALID
UNCERTAIN
STALE
INVALID
```

If assessment quality is not `VALID`, `signed_target_gap` and `performance_state` are unavailable/null.

#### RewardTargetAssessment.attainability

```text
ATTAINABLE
UNREACHABLE_SAFELY
UNKNOWN
```

Attainability is independent of performance state. A valid assessment may therefore be:

```text
performance_state = BELOW_TARGET
signed_target_gap = +12
attainability = UNREACHABLE_SAFELY
```

This preserves the fact that performance is below target while preventing unsafe pursuit.

`RewardTarget` is a threshold/setpoint contract and supports only:

```text
MINIMUM
BAND
```

`MAXIMIZE` is a higher-level strategic optimization objective, not a RewardTarget objective type. Strategic optimization may create or revise versioned RewardTargets only through `RewardTargetAuthority`.

### Canonical signed target-gap semantics

`signed_target_gap` uses this invariant:

```text
positive  = unmet shortfall below the acceptable target region
zero      = current reward is inside the acceptable target region
negative  = current reward is above the acceptable target region
```

For `MINIMUM`:

```text
current < target_value
    performance_state = BELOW_TARGET
    signed_target_gap = target_value - current

current == target_value
    performance_state = WITHIN_TARGET_BAND
    signed_target_gap = 0

current > target_value
    performance_state = ABOVE_TARGET
    signed_target_gap = target_value - current
```

For `BAND [lower, upper]`:

```text
current < lower
    performance_state = BELOW_TARGET
    signed_target_gap = lower - current

lower <= current <= upper
    performance_state = WITHIN_TARGET_BAND
    signed_target_gap = 0

current > upper
    performance_state = ABOVE_TARGET
    signed_target_gap = upper - current
```

The sign convention is frozen architecture. Implementations may not reinterpret it without an explicit superseding ADR.



### Controller behavior from split target semantics

```text
NO_ACTIVE_TARGET
    → observe only
    → no target-seeking pressure

ACTIVE + assessment_quality != VALID
    → hold / gather evidence
    → no signed target gap
    → no target-seeking pressure

ACTIVE + VALID + WITHIN_TARGET_BAND
    → HOLD by default

ACTIVE + VALID + ABOVE_TARGET
    → no target-seeking pressure
    → strategic optimization may still trigger independent evaluation

ACTIVE + VALID + BELOW_TARGET + ATTAINABLE
    → may trigger Decision Evaluation

ACTIVE + VALID + BELOW_TARGET + UNREACHABLE_SAFELY
    → HOLD
    → surface limiting safety/continuity constraints
```

## 5. Reward objective

The long-run economic objective is not raw hashrate and not reward-per-block in isolation.

The M3 target abstraction SHALL be capable of representing a precisely versioned economic quantity such as:

```text
Expected Net Effective Reward Rate
```

The Reward Contract defines the economic quantity and which *realized economic costs* are included.

Do not include probabilistic `Risk`, epistemic/model `Uncertainty`, or duplicated predicted `ActionCost` inside the target metric when those same quantities are already decision penalties under ADR-0006.

Frozen decision evaluation remains:

```text
DUS = (Benefit × Confidence) - (Risk + ActionCost + Uncertainty)
```

This separation prevents double-counting.

The target metric remains subject to hard external constraints:

```text
hardware safety
mining continuity
pool/network validity
telemetry freshness
rollback feasibility
```

The canonical accounting currency/unit is configurable and must be explicit.

### Reward Contract

Every target and realized Reward must bind to a versioned `RewardContract`.

The Reward Contract owns:

- economic metric definition;
- unit/currency;
- pool credited-work semantics;
- included realized operating/transition costs;
- exclusions;
- missing-data behavior;
- maturity/calculation semantics.

### Reward Evaluation Window / Pool Time Block

Every reward evaluation must bind to a first-class `RewardEvaluationWindow`.

It records the exact start/end interval, pool/chain/accounting context, completeness, maturity, and statistical-horizon references.

This enables the project's core requirement to reason about Reward inside a pool/accounting time block without equating that block to a network block interval or controller cadence.

## 6. Time semantics for reward control

Do not collapse these intervals:

```text
Control Evaluation Interval
Statistical Estimation Horizon
Prediction Horizon
Pool Accounting Window
Reward Evaluation Window
Outcome Observation Window
Reward Attribution Window
Network Block Interval
Cooldown / Dwell Interval
```

`RewardEvaluationWindow` is a first-class M3 contract binding the target, reward contract, pool/chain context, data completeness, maturity, and exact start/end interval used for one reward evaluation.

A five-minute evaluation cadence may be used later if accepted by evidence, but M3.0 does not hard-code a universal value.

The controller may evaluate frequently while using longer horizons for confidence and target attainability.

## 7. Outcome / Reward / Learning architecture

This is a first-class M3 subsystem.

```text
Performance / Action Evaluation Window
→ Outcome Observation
→ Outcome Attribution when applicable
→ Reward Evaluation
→ Prediction Error
→ Learning Artifact
→ Update Proposal
→ Independent Verification
→ Promotion Decision
→ Active Version
```

### Outcome supports action and no-action observation

An Outcome is an observation-backed result over a defined evaluation window.

It must support both:

```text
PERFORMANCE_WINDOW
ACTION_ATTRIBUTED
```

`PERFORMANCE_WINDOW` is valid with no Decision, Action, or Execution. This supports target tracking, shadow mode, and no-action baselines.

`ACTION_ATTRIBUTED` additionally references the relevant Decision/Action/Execution and must preserve attribution limitations.

Outcome must identify:

- outcome scope;
- evaluation/observation interval;
- before/reference state when applicable;
- after/current state;
- realized metrics;
- confounding events;
- data quality;
- attribution method/quality when action attribution is claimed.

### Reward owns explicit evaluation

Reward is computed from mature Outcome evidence using a versioned Reward Contract.

Reward is never copied from `PredictionResult`.

### Learning produces proposals, not direct production mutation

Learning may derive evidence-backed proposals for:

- prediction calibration;
- device/algorithm performance models;
- economic estimates;
- action-cost estimates;
- validated lessons;
- future confidence inputs.

Promotion is explicitly separated:

```text
LearningArtifact
→ UpdateProposal
→ Offline / Replay Verification
→ PromotionDecision
→ Active Model / Knowledge Version
```

No LearningArtifact may directly mutate an active production model, policy, controller, or knowledge version.

Learning may not silently alter ADR-0006, policy ownership, or frozen M2 persistence semantics.

## 8. Runtime Strategic Reasoning

A future runtime strategic reasoning layer is required but is advisory.

It may:

- interpret evidence;
- generate hypotheses;
- propose investigation;
- propose experiments;
- recommend strategy;
- explain tradeoffs.

It may not:

- read raw sensors as the authoritative source;
- bypass evidence contracts;
- score/rank outside accepted decision ownership;
- authorize hardware/process actuation;
- rewrite historical evidence.

## 9. Economic / Blockchain Intelligence

A first-class M3 domain intelligence layer is required before meaningful Reward Target shadow evaluation to provide economic/network context such as:

- network difficulty / estimated network hashrate;
- target block interval;
- current height;
- subsidy/emission;
- fee/reward component;
- pool payout scheme and fees;
- pool difficulty and credited work;
- market/economic conversion inputs where approved;
- template/job freshness;
- chain/network regime changes.

It supplies state/evidence/prediction inputs. It does not directly choose actions.

## 10. Execution adapters

Future execution adapters are implementation boundaries, not reasoning authorities.

Expected families:

```text
GPU / NVML adapter
Miner process adapter
Pool / endpoint adapter
OS / runtime adapter
Algorithm/profile adapter where supported
```

Each adapter must expose capability discovery, supported operations, parameter bounds, success/failure semantics, timeouts, and rollback capability.

Locked or unsupported hardware controls must be represented as capabilities, not repeatedly attempted.

## 11. Multi-timescale intelligence

### Fast deterministic layer

- safety interlocks;
- hard constraints;
- actuator bounds;
- emergency protection;
- fail-closed behavior.

### Medium statistical/control layer

- derived metrics;
- state estimation;
- forecasting;
- target tracking;
- constrained optimization;
- prediction-error measurement;
- bounded adaptation.

### Slow strategic layer

- LLM reasoning;
- long-horizon investigation;
- hypothesis/experiment planning;
- human-facing explanation.

Safety must not depend on the slow layer.

## 12. Cross-layer ownership matrix

| Concern | Owner |
|---|---|
| Raw runtime facts | Runtime Observability |
| Evidence semantics | Existing M2 Evidence Foundation |
| Estimated state | Statistical/State Estimation layer |
| Future estimate | Prediction boundary |
| Economic target definition/change/retirement | Reward Target Authority |
| Target controller availability/state | Reward Target Controller |
| Target assessment quality/performance/gap/attainability | Reward Target Assessment subsystem |
| Candidate generation | M2 Candidate Generator |
| Admissibility | M2 Policy |
| DUS scoring | M2 DecisionScorer |
| Ranking | M2 DecisionRanker |
| Decision selection/orchestration | M2 Decision Engine |
| Action/execution safety | Safe Control |
| Device/process command application | Execution Adapter |
| Raw observed runtime/post-action facts | Runtime Observability |
| Outcome windowing/maturity/attribution interpretation | Outcome subsystem |
| Reward calculation | Reward Evaluation subsystem |
| Learning evidence / update proposal | Learning subsystem |
| Production model/knowledge promotion | Explicit Promotion Decision boundary |
| Independent challenge | Experimental Verification |
| Architecture/contracts | Cognitive Systems Architect |
| Final approval | Human owner |


## 12.1 M3 Runtime Evidence Persistence

M3 introduces a logical persistence boundary that is separate from frozen M2 decision persistence.

```text
M2 DecisionEvaluationRepository
    owns frozen M2 decision artifact persistence

M3 Runtime Evidence Persistence
    owns durable M3 runtime/evaluation artifacts
```

`M3 Runtime Evidence Persistence` is the logical owner for durable history of:

```text
RuntimeObservation / runtime events
EconomicState
RewardTarget / target version history
RewardTargetControllerState
RewardTargetAssessment
RewardEvaluationWindow
ActionRequest
ExecutionAuthorization
ExecutionRecord
RollbackRecord
Outcome
RewardEvaluation
PredictionError
LearningArtifact
UpdateProposal
PromotionDecision
```

M3.0 does not choose a database technology.

Persistence must preserve authoritative semantics and provenance; reconstruction must not re-run decision, prediction, reward, learning, or promotion logic.

## 13. Required M3 progression

```text
M3.0  Knowledge / Architecture Foundation
M3.1  Runtime Observability hardening and canonical telemetry contracts
M3.2  State Estimation + Economic / Blockchain Intelligence foundation
M3.3  Prediction / Uncertainty / Calibration foundation
M3.4  Outcome + RewardContract + RewardEvaluationWindow foundation
M3.5  Reward Target Authority + Reward Target Controller in observation/shadow form
M3.6  Learning + Replay / Backtesting + Promotion Gate
M3.7  Safe Control + ExecutionAuthorization + execution adapters in simulation/shadow
M3.8  Bounded controlled execution
M3.9  Reward-target closed-loop optimization
M3.x  Runtime strategic reasoning expansion
```

Exact phase numbering may be changed by accepted architecture, but Reward Target Control must not be removed or reduced to an optional feature.

## 14. Architectural completion criterion

MiningGuardian is not complete as an autonomous cognitive control system until it can safely and audibly perform:

```text
observe reality
→ estimate state
→ predict
→ decide
→ execute safely
→ observe Outcome
→ compute realized Reward
→ compare Reward against an explicit Target
→ learn from prediction/Outcome error
→ adapt without violating safety or continuity
```
