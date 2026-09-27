# M3 Control Safety

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

Define the safety architecture for any future transition from M2 decision output to runtime action.

M3.0 grants no live execution authority.

## 2. Safety priority

When objectives conflict, the control system must preserve this ordering unless an accepted ADR explicitly changes it:

```text
Hardware Safety
> Mining Continuity
> Evidence Quality / Observability
> Constraint Compliance
> Net Effective Reward Objective
> Energy Efficiency
> Exploration / Learning
```

Reward Target pursuit is subordinate to safety and continuity.

## 3. Reward Target Controller safety rule

A Reward Target is an objective, never a command.

Target creation/change/retirement belongs to a separate `RewardTargetAuthority`.

The Reward Target Controller consumes only an `ACTIVE` target and exposes controller state:

```text
NO_ACTIVE_TARGET
ACTIVE
ASSESSMENT_UNAVAILABLE
```

When an assessment is available, it is represented separately as `RewardTargetAssessment` with:

```text
assessment_quality =
    VALID | UNCERTAIN | STALE | INVALID

performance_state when VALID =
    BELOW_TARGET | WITHIN_TARGET_BAND | ABOVE_TARGET

attainability =
    ATTAINABLE | UNREACHABLE_SAFELY | UNKNOWN
```

It may request/trigger Decision evaluation only when allowed by the assessment invariants.

It may not:

- create, lower, widen, or otherwise redefine its own target;
- bypass frozen M2 Policy;
- bypass DUS scoring/ranking;
- authorize Action;
- execute;
- lower safety limits to reach target;
- restart/switch repeatedly to chase short-window noise.

`attainability = UNREACHABLE_SAFELY` is a valid successful safety conclusion.

## 4. Action path

Future execution must conceptually follow:

```text
DecisionResult
→ ActionRequest
→ Capability Gate
→ Execution Safety Gate
→ Freshness Gate
→ Stability / Rate Gate
→ Rollback Gate
→ Human Approval Gate when required
→ ExecutionAuthorization
→ Execution Adapter
→ ExecutionRecord
→ Outcome Observation
→ Reward Evaluation
```

No stage may be skipped merely because reward is below target.

### Frozen M2 Policy vs Execution Safety

`M2 DecisionPolicy` owns candidate admissibility before selection.

`Execution Safety Gate` owns only runtime execution preconditions after a Decision exists.

It must not re-score, re-rank, or substitute a different candidate.

If current state, capability, freshness, or constraints invalidate the selected Decision:

```text
ExecutionAuthorization = REEVALUATION_REQUIRED
→ return to Decision Engine
```

Safe Control blocks or returns for reevaluation; it does not silently re-decide.


## 5. Safe operating envelope

Define per controllable domain:

```text
hard bounds
soft bounds
warning region
forbidden region
capability limits
telemetry requirements
rollback requirements
```

Potential dimensions:

- temperature;
- thermal throttling;
- power draw/limit;
- clocks;
- miner health;
- pool connectivity;
- telemetry freshness;
- restart frequency;
- switching frequency;
- action magnitude.

Do not infer hardware-safe limits from short successful experiments.

## 6. Capability discovery

Before any action:

- verify adapter exists;
- verify capability is writable;
- verify range;
- verify permissions;
- verify restart requirement;
- verify rollback support;
- verify observed/current setting where applicable.

Unsupported fan/power/clock control must fail closed as a capability fact.

## 7. Anti-churn controls

Any target-seeking control must include applicable:

```text
deadband
hysteresis
minimum dwell
cooldown
rate limits
minimum expected improvement
switching penalty
restart budget
```

The Reward Target Controller must not oscillate between candidates when target gap is small or uncertain.

## 8. ActionCost

ActionCost includes more than electricity:

```text
restart downtime
lost hashing time
warmup/ramp
pool reconnect
job reacquisition
stale/rejected work risk
switching churn
instability risk
rollback cost
opportunity cost
measurement discontinuity
```

Target pursuit must account for ActionCost through the frozen decision model.

## 9. Restart rule

Restart is a high-cost intervention, not a normal tuning primitive.

Any future restart-capable policy must define:

- reason;
- minimum evidence;
- expected benefit;
- downtime estimate;
- restart budget;
- cooldown;
- recovery criteria;
- alternative non-restart actions;
- rollback/failure behavior.

Repeated restart behavior is evidence of controller failure unless explicitly justified.

## 10. Safe exploration ladder

```text
offline analysis
→ replay
→ simulation
→ shadow mode
→ bounded experiment
→ limited execution
→ broader execution
```

Production mining must not be the first exploration environment.

## 11. Rollback

For actions requiring rollback:

```text
pre-action state
action identity
expected effect
observation window
failure criteria
rollback trigger
rollback action
rollback timeout
post-rollback verification
```

Issuing a reverse command is not proof of rollback success.

## 12. Target pursuit and uncertainty

Target-seeking pressure requires a valid assessment.

```text
NO_ACTIVE_TARGET
    → HOLD / observe
    → no target-seeking pressure

ASSESSMENT_UNAVAILABLE
    → HOLD / gather evidence
    → no target-seeking pressure

assessment_quality = UNCERTAIN | STALE | INVALID
    → signed_target_gap = null
    → HOLD / gather evidence / authority review
    → no target-seeking pressure

VALID + WITHIN_TARGET_BAND
    → HOLD by default

VALID + ABOVE_TARGET
    → no target-seeking pressure

VALID + BELOW_TARGET + ATTAINABLE
    → Decision Evaluation may be requested

VALID + BELOW_TARGET + UNREACHABLE_SAFELY
    → HOLD
    → surface limiting safety/continuity constraints
```

The controller must never convert uncertainty, invalidity, staleness, or unattainability into aggressive action pressure.

## 13. LLM boundary

Never:

```text
LLM → actuator
```

LLM reasoning may propose investigations/strategies only.

All runtime execution must pass deterministic, inspectable gates.

## 14. Fail-safe behavior

Possible safe responses include:

- hold current stable configuration;
- disable autonomous action;
- revert to known-safe profile;
- request human review;
- isolate failed adapter;
- continue observation only.

Restart is not a universal fail-safe.

## 15. Control acceptance gate

No live control phase may begin until:

- contracts are accepted;
- telemetry is reliable;
- target/reward semantics are accepted;
- outcome attribution exists;
- action cost is measurable;
- simulation/replay exists;
- rollback is tested;
- read-only adversarial verification passes;
- user explicitly approves execution scope.
