# M3 Glossary

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


## Purpose

Canonical M3 meanings. These definitions prevent semantic drift between observability, statistical learning, decision logic, safe control, reward targeting, outcome evaluation, and learning.

## Core ontology

| Term | Canonical meaning |
|---|---|
| Telemetry | Raw observed runtime measurement from a defined source. |
| Derived Metric | Deterministic transformation/aggregation of telemetry. |
| Evidence | Traceable runtime or historical fact usable to support/contradict a claim. |
| Claim | Evidence-grounded statement about the system/world. |
| Hypothesis | Testable possible explanation or future-relevant proposition. |
| Estimated State | Inferred representation of current system condition. |
| Prediction | Estimate of a future quantity/state. |
| Confidence | Reliability/strength assigned under an explicit interpretation. |
| Uncertainty | Quantified lack of certainty. |
| Decision | Selected intended course of action. |
| Action | Requested control change. |
| Execution | Actual attempt to perform an Action. |
| Outcome | Observation-backed result over a defined evaluation window; may be a no-action performance-window outcome or an action-attributed outcome. |
| Reward | Versioned numeric economic evaluation of a mature observed Outcome under an explicit Reward Contract. |
| Prediction Error | Difference between a Prediction and mature observed target/Outcome. |
| Policy | Constraints determining admissible Actions/Candidates. |
| Learning Artifact | Evidence-backed record of what changed in knowledge/model/calibration after mature Outcome evaluation. |

## Reward-target ontology

| Term | Canonical meaning |
|---|---|
| Reward Target | Explicit desired economic performance objective authorized by a separate Target Authority under stated constraints and units. |
| Reward Target Authority | Authority that creates, changes, retires, and versions Reward Targets; separate from both M2 Policy and the runtime target tracker. |
| Reward Target Controller | Layer that consumes an authorized active target, exposes controller availability/state, obtains RewardTargetAssessment, and may request reevaluation; it cannot redefine its own target. |
| Target Band | Tolerance interval considered acceptable around the target. |
| Signed Target Gap | Canonical signed distance from the acceptable target region: positive = unmet shortfall, zero = acceptable region, negative = above acceptable region; unavailable when assessment quality is not VALID. |
| Reward Target Lifecycle | Definition lifecycle: DRAFT, ACTIVE, EXPIRED, RETIRED, SUPERSEDED. |
| Reward Target Controller State | Controller availability: NO_ACTIVE_TARGET, ACTIVE, ASSESSMENT_UNAVAILABLE. |
| Reward Target Performance State | Valid assessment classification: BELOW_TARGET, WITHIN_TARGET_BAND, ABOVE_TARGET. |
| Assessment Quality | Evaluation validity: VALID, UNCERTAIN, STALE, INVALID. |
| Target Attainability | Evidence-backed safety/feasibility classification of whether the active target can be pursued within accepted safety, continuity, action-cost, and capability constraints: ATTAINABLE, UNREACHABLE_SAFELY, or UNKNOWN. |
| Current Reward State | Current estimated economic performance state, explicitly distinguished from realized Reward for a completed Outcome. |
| Reward Target Assessment | Versioned evaluation of current reward against one active RewardTarget and one RewardEvaluationWindow, carrying assessment quality, optional performance state, optional signed target gap, and attainability. |
| Reward Contract | Versioned definition of the economic reward metric, units, included realized costs, exclusions, maturity rules, and calculation semantics. |
| Expected Net Effective Reward Rate | Expected economically credited reward rate under a Reward Contract; probabilistic Risk/Uncertainty penalties remain separate ADR-0006 decision terms unless explicitly superseded. |
| Realized Reward | Reward computed from mature observed Outcome evidence. |
| Strategic Optimization Objective | Higher-level objective such as MAXIMIZE reward; it may inform target creation but is not itself a RewardTarget setpoint/band. |

## Time ontology

| Term | Meaning |
|---|---|
| Event Time | When the underlying real-world event occurred. |
| Observation Time | When a source recorded the observation. |
| Ingestion Time | When MiningGuardian received it. |
| Processing Time | When a component processed it. |
| Decision Time | When a Decision was produced. |
| Action Time | When an Action was requested. |
| Execution Time | When execution was attempted. |
| Outcome Window | Interval over which performance facts are observed; it does not require an Execution. |
| Reward Evaluation Window | First-class interval binding target, Reward Contract, pool/chain/accounting context, data completeness, and maturity for one reward evaluation. |
| Reward Attribution Window | Interval whose mature Outcome is attributed to an action/reward calculation when attribution is applicable. |
| Control Evaluation Interval | How often target/control state is reevaluated. |
| Statistical Horizon | Historical interval used to estimate current/trend state. |
| Prediction Horizon | Future interval the Prediction concerns. |
| Pool Accounting Window | Pool-defined or system-defined aggregation interval for credited work. |
| Network Block Interval | Protocol/network block timing concept; not the same as a controller window. |
| Cooldown | Minimum wait after relevant action before another related action. |
| Dwell Time | Minimum time a state/profile must remain active. |

## Control ontology

| Term | Meaning |
|---|---|
| Plant | Runtime/physical system being controlled. |
| Controller | Logic mapping state/objectives/constraints to requested control behavior. |
| Actuator | Mechanism applying a control change. |
| Safe Operating Envelope | Allowed region of state/action under current safety constraints. |
| Deadband | Region where no action is taken. |
| Hysteresis | Different enter/exit thresholds to reduce toggling. |
| Rate Limit | Bound on action frequency/magnitude change. |
| Rollback | Verified restoration toward a known-safe configuration/state. |
| Execution Authorization | Explicit post-decision authorization result after capability, execution-safety, freshness, stability/rate, rollback, and human-approval gates. |
| Update Proposal | Proposed model/knowledge/configuration update derived from LearningArtifact; not active until promoted. |
| Promotion Decision | Explicit verified decision that approves/rejects an Update Proposal for activation. |
| M3 Runtime Evidence Persistence | Logical persistence boundary for durable M3 runtime/evaluation artifacts, separate from frozen M2 DecisionEvaluationRepository. |
| Saturation | Requested control reaches/exceeds capability limit. |
| Stability | Controlled behavior remains bounded and acceptable. |

## Economic/blockchain ontology

| Term | Meaning |
|---|---|
| Raw Hashrate | Miner/device-reported compute rate. |
| Effective Hashrate | Estimate of economically credited useful work rate under explicit source/window semantics. |
| Accepted Work | Pool-credited shares/work. |
| Rejected Work | Submitted work rejected by pool. |
| Stale Work | Work valid in form but too late/outdated for credit under pool semantics. |
| Share Difficulty | Difficulty weight associated with submitted share/work. |
| Network Difficulty | Chain/network mining difficulty. |
| Block Reward | Protocol subsidy/emission plus applicable fee component; not itself miner reward rate. |
| Pool Payout Policy | Rules mapping credited work to miner payout. |
| Action Cost | Restart, warmup, reconnect, switching, downtime, instability, rollback and opportunity costs—not electricity alone. |

## Mandatory non-equivalences

```text
Telemetry ≠ Derived Metric
Derived Metric ≠ Estimated State
Estimated State ≠ Prediction
Prediction ≠ Outcome
Outcome ≠ Reward
PerformanceWindowOutcome ≠ ActionAttributedOutcome
Expected Reward ≠ Realized Reward
Current Reward State ≠ Realized Reward
Target ≠ Prediction
Reward Target Lifecycle ≠ Reward Target Performance State
Assessment Quality ≠ Target Attainability
Signed Target Gap ≠ Decision
Decision ≠ Action
Action ≠ Execution
Execution ≠ Outcome
Confidence ≠ Probability unless calibrated
Missing ≠ Zero
Stale ≠ Missing
Reward Target Authority ≠ M2 Policy
Reward Target Authority ≠ Reward Target Controller
Reward Target Controller State ≠ Reward Target Assessment
Reward Target Controller ≠ Decision Engine
Reward Target Controller ≠ Safe Control
Execution Authorization ≠ M2 Policy
Learning Artifact ≠ Active Production Update
LLM reasoning ≠ control authority
```

## Naming rule

New M3 interfaces, storage entities, tests, and telemetry must use these terms consistently. If a proposed name overloads one of these concepts, fix the name or create an ADR before implementation.
