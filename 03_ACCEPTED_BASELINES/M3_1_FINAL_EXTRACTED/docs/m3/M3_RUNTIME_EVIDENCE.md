# M3 Runtime Evidence

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

Define the evidence needed to reconstruct what MiningGuardian observed, inferred, decided, executed, measured, rewarded, and learned.

## 2. Evidence chain

M3 should be able to trace:

```text
Runtime Source
→ Telemetry
→ Data Quality
→ Derived Metric
→ Estimated State / EconomicState
→ Evidence
→ Claim/Hypothesis
→ Prediction
→ RewardTarget
→ RewardTargetControllerState
→ RewardTargetAssessment
→ Decision
→ ActionRequest
→ ExecutionAuthorization
→ ExecutionRecord
→ Outcome
→ RewardEvaluation
→ PredictionError
→ LearningArtifact
```

Not every cycle has every artifact, but identities must never be inferred from accidental ordering.

## 3. Runtime observation metadata

Capture where applicable:

```text
observation_id
source
source_instance
signal
value
unit
event_time
observation_time
ingestion_time
quality
freshness
session_id
correlation_id
schema_version
```

Missing must remain distinguishable from zero.

## 4. Mining evidence domains

### Hardware
temperature, hotspot if available, throttle reason, power, power limit, core/memory clocks, utilization, performance state, capability availability.

### Miner
version, algorithm, process state, raw hashrate, uptime, job updates, accepted/rejected/stale shares, errors, restart events.

### Pool/network
endpoint, connection state, latency semantics, reconnects, share response, job age, template freshness, pool difficulty.

### Blockchain/economic
network difficulty, block interval, height, reward components, pool payout semantics, fees, approved conversion inputs.

### Transition
requested config, observed config, restart/switch timing, reconnect, warmup/ramp, stabilization.

## 5. Reward Target Authority, lifecycle, controller-state, and assessment evidence

Every target definition/change/retirement should capture:

```text
reward_target_id
target_authority_id
objective_type
reward_contract_version
old_version?
new_version
reason
lifecycle_status
approved/effective time
expiry/retirement/supersession time?
authority
```

Canonical lifecycle:

```text
DRAFT
ACTIVE
EXPIRED
RETIRED
SUPERSEDED
```

The runtime Reward Target Controller must not alter these records.

Every controller-state snapshot should capture:

```text
reward_target_controller_state_id
evaluated_at
controller_status
active_reward_target_id?
latest_assessment_id?
reason?
```

Every target assessment should capture:

```text
reward_target_assessment_id
reward_target_id
reward_window_id
evaluated_at
current reward estimate
uncertainty
assessment_quality
performance_state?
signed_target_gap?
attainability
attainability_reason?
evidence refs
prediction refs
decision evaluation required
```

Never persist one overloaded enum that mixes target lifecycle, controller availability, assessment quality, reward performance, and attainability.

## 6. Before-decision / before-action snapshots

For significant decisions/actions capture applicable:

- telemetry quality/freshness;
- estimated state;
- economic state;
- current target state;
- current configuration;
- prediction;
- uncertainty;
- constraints/capabilities.

## 7. Action/execution evidence

Trace:

```text
decision_id
candidate_id
action_id
authorization_id
authorization_status
authorization_evaluated_at
authorization_expires_at?
execution_id?
adapter_id?
requested parameters
authorized/rejected gates
attempt timestamp?
completion timestamp?
status
error/timeout
rollback_id?
observed post-command setting?
```

Requested state is not observed state.

## 8. Reward Evaluation Window / Pool Time Block evidence

Capture:

```text
reward_window_id
target_id?
reward_contract_version
window start/end
pool/endpoint
chain/algorithm
pool accounting semantics
statistical/prediction horizon refs
data completeness
maturity
quality
```

Never infer that pool accounting window, network block interval, control interval, and Reward Evaluation Window are the same.

## 9. Outcome evidence

Capture:

```text
outcome_id
outcome_scope
reward_window_id
execution_id?
action_id?
decision_id?
window start/end
before state
after state
realized effective work
accepted/rejected/stale work
power/energy
thermal state
pool/network state
downtime
warmup/recovery
confounders
quality
attribution confidence/quality
baseline/reference window if ACTION_ATTRIBUTED
reference method
baseline compatibility
maturity
```

## 10. Reward evidence

Capture:

```text
reward_evaluation_id
reward_contract_version
economic unit
gross credited reward/work basis
explicit operating cost
realized_transition_cost
realized_restart_cost
realized_switching_cost
other realized cost components allowed by RewardContract
realized reward
quality
limitations
```

The raw component evidence must remain available for audit.

Do not label realized reward costs as ADR-0006 `ActionCost`; ADR-0006 ActionCost is a decision-time predicted penalty artifact.

## 11. Prediction error evidence

After maturity:

```text
prediction_id
outcome/observed-target ref
prediction time
horizon
predicted value
observed value
error metric
error value
quality
```

## 12. Restart evidence

A restart must expose enough timestamps to estimate its actual cost:

```text
restart requested
process stop
process start
pool reconnect
first valid job
hashrate resumed
effective work recovered
stabilized
```

## 13. Switching evidence

Capture:

```text
old target/profile/pool
new target/profile/pool
switch request
execution
disconnect/reconnect
warmup
stabilization
post-switch outcome
rollback
```

## 14. Strategic reasoning evidence

Runtime LLM reasoning, when introduced, must be distinguishable from facts.

Record:

- input evidence refs;
- hypothesis/proposal;
- model/provider/version where appropriate;
- limitations;
- human/automated disposition.

Never store model prose as raw evidence.

## 15. Learning evidence

A learning update must trace back to mature Outcome/Reward/PredictionError.

Store:

```text
learning artifact id
what was learned
source evidence
update proposal id if one exists
current version
proposed version
verification status
promotion decision id if evaluated
active version after promotion if approved
```

Observed learning evidence must remain separate from production activation.


## 16. Runtime correlation chain

Where applicable, evidence should preserve this identity path:

```text
RuntimeObservation
→ EstimatedState / EconomicState / Prediction
→ RewardTarget
→ RewardTargetControllerState
→ RewardTargetAssessment
→ DecisionContext / Decision
→ ActionRequest
→ ExecutionAuthorization
→ ExecutionRecord
→ RollbackRecord?
→ RewardEvaluationWindow
→ Outcome
→ RewardEvaluation
→ PredictionError
→ LearningArtifact
→ UpdateProposal
→ PromotionDecision
```

Missing optional links must remain explicitly absent; never synthesize identities from order or timing proximity.

## 17. M3 Runtime Evidence Persistence

Logical durable owner:

```text
M3 Runtime Evidence Persistence
```

This boundary is separate from frozen M2 DecisionEvaluationRepository and owns durable M3 runtime/evaluation history where retention policy requires it.

It must support audit/replay of:

```text
runtime observations/events
EconomicState
RewardTarget versions
RewardTargetControllerState
RewardTargetAssessment
RewardEvaluationWindow
ActionRequest / ExecutionAuthorization / ExecutionRecord / RollbackRecord
Outcome / RewardEvaluation
PredictionError
LearningArtifact / UpdateProposal / PromotionDecision
```

It must preserve identities, timestamps, provenance, versions, and historical immutability/correction history.

It must never reconstruct M2 Decision artifacts by rerunning M3 logic.

## 18. Immutability and corrections

Historical observations/outcomes should be append-only or correction-traceable where practical.

Distinguish:

```text
original fact
correction
derived interpretation
later annotation
```

## 19. Retention tiers

Architecture should support:

- high-resolution short-term telemetry;
- medium-term aggregates;
- long-term experiments/outcomes/rewards;
- durable decision/action/audit evidence;
- model/learning provenance.

Do not downsample away critical safety or transition events.

## 20. Observability overhead

Evidence collection must be measured for CPU, memory, disk, network, and polling overhead.

Mining workload stability remains a constraint.
