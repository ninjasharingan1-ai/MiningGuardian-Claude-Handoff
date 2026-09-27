# M3 Data Contracts

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

Define architecture-level contracts required for M3 without prematurely locking implementation classes or database tables.

## 2. Contract principles

Every M3 artifact must identify:

```text
identity
semantic type
producer/owner
timestamp semantics
units where numeric
source/provenance
quality/freshness
version
relationships/correlation IDs
```

Persistence/transport must not change meaning.

## 3. RuntimeObservation contract

Minimum conceptual fields:

```text
observation_id
source_type
source_instance
signal_name
value
unit
event_time
observation_time
ingestion_time
quality_state
freshness
session_id?
correlation_id?
schema_version
```

Quality states should support at least:

```text
VALID
MISSING
STALE
DELAYED
DUPLICATED
OUT_OF_ORDER
CORRUPTED
OUT_OF_RANGE
RESET_OR_DISCONTINUOUS
SOURCE_UNAVAILABLE
UNKNOWN
```

## 4. EstimatedState contract

```text
state_id
state_type
value / structured_state
estimated_at
effective_time
source_observation_ids
method_id/version
freshness
confidence?
uncertainty?
quality_state
limitations
```

An EstimatedState must never be serialized as raw telemetry.

## 5. Prediction contract

M2 `PredictionResult` semantics remain future estimates.

M3 model-specific prediction artifacts may enrich, but not overload, the M2 boundary.

Required conceptual metadata:

```text
prediction_id
target
prediction_time
target_time / horizon
point_estimate?
interval/distribution?
confidence semantics
uncertainty semantics
model_id/version
feature_contract_version
input cutoff time
limitations
```

## 6. RewardContract

Reward semantics are first-class and versioned.

```text
reward_contract_id
version
reward_metric_name
economic_unit
gross_reward_basis
credited_work_semantics
pool_payout_semantics
included_realized_costs
excluded_decision_penalties
missing_data_policy
maturity_rule
calculation_rule/version
effective_from
effective_until?
```

Mandatory separation:

```text
Reward Contract economic metric
≠
ADR-0006 Risk / Uncertainty penalties
```

A Reward Contract may include *realized* transition or operating costs where explicitly defined.

It must not duplicate probabilistic `Risk`, epistemic/model `Uncertainty`, or predicted `ActionCost` that are already decision penalties under ADR-0006.

## 7. RewardTargetAuthority contract

Target creation/change/retirement is separate from target tracking.

```text
target_authority_id
authority_type
allowed_target_basis
allowed_economic_units
allowed_objective_types
creation_rules
change_rules
retirement_rules
human_approval_required?
version
```

The authority produces versioned RewardTarget definitions.

A runtime Reward Target Controller cannot modify this authority or redefine an active target.

## 8. RewardTarget contract

Reward target is first-class.

```text
reward_target_id
target_name
objective_type
economic_unit
target_value?
target_band_lower?
target_band_upper?
target_basis
reward_contract_version
effective_from
effective_until?
evaluation_interval
minimum_statistical_horizon
safety_constraints_ref
continuity_constraints_ref
target_authority_id
lifecycle_status
version
```

`objective_type` must be explicit and is limited to:

```text
MINIMUM
BAND
```

`MAXIMIZE` is not a RewardTarget objective type. It is a strategic optimization objective that may inform target creation through RewardTargetAuthority.

Do not allow a target with undefined economic unit, reward basis, authority, or Reward Contract.

Conditional target requirements:

```text
MINIMUM
    requires target_value

BAND
    requires target_band_lower + target_band_upper
    requires lower <= upper
```

RewardTarget definition lifecycle is separate from runtime assessment.

Canonical `lifecycle_status`:

```text
DRAFT
ACTIVE
EXPIRED
RETIRED
SUPERSEDED
```

Only `ACTIVE` targets may be consumed by RewardTargetController.

## 9. RewardEvaluationWindow / Pool Time Block contract

One reward evaluation must use an explicit first-class window.

```text
reward_window_id
reward_target_id?
reward_contract_version
window_start
window_end
pool_id / endpoint?
chain / algorithm?
worker/session?
pool_accounting_semantics
statistical_horizon_refs
prediction_horizon_refs
data_completeness
maturity_status
quality
source_refs
```

A pool-provided accounting block/window may be referenced, but must not be silently treated as the same thing as network block interval, controller interval, or statistical horizon.

## 10. RewardTargetControllerState contract

Controller state is valid even when no target exists.

```text
reward_target_controller_state_id
evaluated_at
controller_status
active_reward_target_id?
latest_assessment_id?
reason?
evidence_refs
```

Canonical `controller_status`:

```text
NO_ACTIVE_TARGET
ACTIVE
ASSESSMENT_UNAVAILABLE
```

Invariants:

```text
NO_ACTIVE_TARGET
    active_reward_target_id = null
    latest_assessment_id = null
    target-seeking decision pressure = false

ASSESSMENT_UNAVAILABLE
    active_reward_target_id is required
    latest_assessment_id = null
    target-seeking decision pressure = false

ACTIVE
    active_reward_target_id is required
    latest_assessment_id is required
```

These controller states are mutually exclusive under the invariants above.

No sentinel/fake target IDs are permitted.

## 11. RewardTargetAssessment contract

Assessment exists only for an actual active target.

```text
reward_target_assessment_id
reward_target_id
reward_window_id
evaluated_at
current_reward_state?
current_reward_uncertainty?
signed_target_gap?
performance_state?
assessment_quality
attainability
attainability_reason?
freshness
evidence_refs
prediction_refs
decision_evaluation_required
```

Canonical `assessment_quality`:

```text
VALID
UNCERTAIN
STALE
INVALID
```

Canonical `performance_state` when `assessment_quality = VALID`:

```text
BELOW_TARGET
WITHIN_TARGET_BAND
ABOVE_TARGET
```

Canonical `attainability`:

```text
ATTAINABLE
UNREACHABLE_SAFELY
UNKNOWN
```

Quality invariants:

```text
assessment_quality = VALID
    current_reward_state is required
    signed_target_gap is required
    performance_state is required

assessment_quality != VALID
    signed_target_gap = null
    performance_state = null
    attainability = UNKNOWN
    decision_evaluation_required = false
```

`current_reward_uncertainty` may remain optional at architecture level; an implementation-specific statistical contract may require it for methods that produce uncertainty.

Attainability is not performance state:

```text
BELOW_TARGET + UNREACHABLE_SAFELY
```

is valid and means the target is missed but may not be pursued through unsafe actions.

### Canonical signed target-gap semantics

The sign convention is:

```text
positive  = unmet shortfall
zero      = inside acceptable region
negative  = above acceptable region
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

Decision-pressure invariants:

```text
VALID + WITHIN_TARGET_BAND
    decision_evaluation_required = false by target pressure alone

VALID + ABOVE_TARGET
    decision_evaluation_required = false by target pressure alone

VALID + BELOW_TARGET + ATTAINABLE
    decision_evaluation_required may be true

VALID + BELOW_TARGET + UNREACHABLE_SAFELY
    decision_evaluation_required = false by target pressure alone
```

The Reward Target Controller may still request unrelated Decision Evaluation for independent non-target reasons, but that must not be represented as target-seeking pressure.

## 12. ActionRequest contract

Must remain separate from M2 Decision.

```text
action_id
decision_id
candidate_id
action_type
parameters
requested_at
requested_by
required_capability
risk_class
rollback_required
```

## 13. ExecutionAuthorization contract

This is a post-decision runtime authorization boundary, not M2 candidate Policy.

```text
authorization_id
action_id
evaluated_at
capability_gate
execution_safety_gate
freshness_gate
stability_rate_gate
rollback_gate
human_approval_gate?
authorization_status
reasons
expires_at?
```

Suggested authorization statuses:

```text
AUTHORIZED
DENIED
EXPIRED
REVOKED
REEVALUATION_REQUIRED
```

If runtime state changes make the selected Decision unsafe or stale, return `REEVALUATION_REQUIRED` to the Decision Engine rather than re-deciding inside Safe Control.

## 14. ExecutionRecord contract

Create an ExecutionRecord only for an actual execution attempt.

```text
execution_id
action_id
authorization_id
adapter_id
attempted_at
completed_at?
status
observed_capability
result_metadata
error?
timeout?
correlation_id
```

Execution-only status vocabulary:

```text
EXECUTING
SUCCEEDED
FAILED
TIMED_OUT
ABORTED
UNKNOWN
```

`REQUESTED`, `AUTHORIZED`, and `BLOCKED` do not belong to execution state.

Command dispatch is not success.

## 15. RollbackRecord contract

Rollback is separately auditable.

```text
rollback_id
execution_id
trigger
requested_at
attempted_at?
completed_at?
status
rollback_action
post_rollback_state_ref?
error?
```

Suggested status vocabulary:

```text
REQUESTED
EXECUTING
SUCCEEDED
FAILED
TIMED_OUT
NOT_REQUIRED
```

## 16. Outcome contract

Outcome supports action and no-action observation.

```text
outcome_id
outcome_scope
reward_window_id
execution_id?
action_id?
decision_id?
observation_window_start
observation_window_end
baseline_window_ref?
before_state_ref?
after_state_ref
realized_metrics
confounders
attribution_method?
attribution_quality?
data_quality
maturity_status
observed_at
```

Canonical `outcome_scope`:

```text
PERFORMANCE_WINDOW
ACTION_ATTRIBUTED
```

For `PERFORMANCE_WINDOW`, execution/action/decision references may be absent.

For `ACTION_ATTRIBUTED`, the relevant references are required and attribution limitations must remain explicit.

Before an `ACTION_ATTRIBUTED` Outcome may feed Learning or Promotion, it must also declare an auditable reference basis:

```text
baseline_window_ref or reference_expectation_ref
reference_state_ref?
reference_method
baseline_compatibility
known_confounders
attribution_quality
```

A post-action difference without a reference basis may be recorded as observed performance but must not be treated as validated action attribution.

No Outcome may be created by copying a Prediction.

## 17. RewardEvaluation contract

```text
reward_evaluation_id
outcome_id
reward_window_id
reward_contract_version
evaluated_at
economic_unit
components
gross_effective_reward
included_realized_costs
realized_transition_cost?
realized_restart_cost?
realized_switching_cost?
realized_operating_cost?
realized_reward
quality
limitations
```

Reward calculation must be deterministic for the same mature Outcome + Reward Window + Reward Contract version unless the contract explicitly defines otherwise.

Probabilistic Risk/Uncertainty penalties are not part of realized Reward by default; they remain decision-layer ADR-0006 terms.

## 18. PredictionError contract

```text
prediction_error_id
prediction_id
outcome_id or observed_target_ref
target
horizon
predicted_value
observed_value
error_metric
error_value
evaluated_at
quality
```

Prediction Error may be computed only after target maturity.

## 19. LearningArtifact contract

```text
learning_artifact_id
source_outcome_ids
source_reward_ids
source_prediction_error_ids
lesson_type
proposed_change_summary
created_at
verification_status
limitations
```

LearningArtifact records evidence-backed knowledge; it does not mutate active production state.

## 20. UpdateProposal contract

```text
update_proposal_id
learning_artifact_ids
target_component
current_version
proposed_version
proposed_change
expected_benefit
risk
validation_plan
created_at
```

## 21. PromotionDecision contract

```text
promotion_decision_id
update_proposal_id
verification_evidence_refs
decision
reason
approved_version?
decided_at
authority
```

Promotion flow:

```text
LearningArtifact
→ UpdateProposal
→ Offline / Replay Verification
→ PromotionDecision
→ Active Version
```

No direct `LearningArtifact → Active Version` path is allowed.

## 22. EconomicState contract

Future economic/blockchain intelligence should expose an explicit state:

```text
economic_state_id
chain/algorithm
network_difficulty
network_hashrate_estimate?
block_interval
block_reward_components
pool_payout_policy
pool_fee
pool/share difficulty
credited_work_state
price/conversion_input? 
job/template freshness
observed_at
freshness
quality
source_refs
```

Unknown values remain unknown; do not invent defaults.

## 23. Capability contract

Execution adapters must expose capabilities before use:

```text
adapter_id
capability_name
available
read_only / writable
supported_range?
unit?
requires_restart?
rollback_supported
reason_if_unavailable
observed_at
```

Locked laptop controls are valid `available = false` capability facts.

## 24. Correlation chain

M3 must be able to trace, where applicable:

```text
RuntimeObservation
→ Evidence / EstimatedState / EconomicState
→ Prediction
→ RewardTarget
→ RewardTargetControllerState
→ RewardTargetAssessment
→ DecisionContext
→ Decision
→ ActionRequest
→ ExecutionAuthorization
→ ExecutionRecord
→ RollbackRecord?
→ RewardEvaluationWindow
→ Outcome
→ RewardEvaluation
→ Target Comparison
→ PredictionError
→ LearningArtifact
→ UpdateProposal
→ Verification Evidence
→ PromotionDecision
→ future target/state/prediction/strategy
```

Not every cycle includes every artifact.

No layer should infer missing identity relationships from ordering alone.

## 25. Persistence rule

M2 decision persistence remains untouched.

Frozen owner:

```text
M2 DecisionEvaluationRepository
```

New logical M3 owner:

```text
M3 Runtime Evidence Persistence
```

M3 Runtime Evidence Persistence owns durable M3 runtime/evaluation artifacts including telemetry/event history where retained, EconomicState, RewardTarget history, RewardTargetControllerState, RewardTargetAssessment, RewardEvaluationWindow, Action/Execution/Rollback records, Outcome, RewardEvaluation, PredictionError, LearningArtifact, UpdateProposal, and PromotionDecision.

It must not overload `PredictionResult`, reuse frozen M2 database fields for new semantics, or make M2 reconstruction depend on M3 runtime stores.

Implementation technology and concrete repository split remain deferred to the relevant implementation phase.

## 26. Schema evolution

Every new persisted M3 contract requires:

- explicit version;
- migration/backward-compatibility decision;
- round-trip tests;
- authoritative field definitions;
- no reconstruction-side re-cognition.
