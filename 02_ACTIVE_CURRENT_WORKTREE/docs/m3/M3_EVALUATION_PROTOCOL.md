# M3 Evaluation Protocol

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

Define how M3 claims are validated before they become accepted architecture, models, target logic, or runtime control.

## 2. Verification principle

```text
plausible reasoning ≠ verified behavior
passing tests ≠ complete evidence
prediction ≠ outcome
```

The first independent verification pass is read-only.

## 3. Evidence ladder

Use the strongest applicable evidence:

```text
deterministic contract tests
→ mathematical verification
→ simulation
→ historical replay / backtesting
→ shadow mode
→ bounded controlled experiment
→ production runtime evidence
```

Agent narrative is not ground truth.

## 4. Standard result statuses

```text
PASS
FAIL
INCONCLUSIVE
BLOCKED
NOT_APPLICABLE
```

Never convert `INCONCLUSIVE` into `PASS`.

## 5. Reward Target Controller evaluation

Before target control can influence runtime:

### Contract tests

Verify:

- target is produced by an independent RewardTargetAuthority;
- controller cannot mutate active target definition;
- RewardTarget objective type is only `MINIMUM` or `BAND`;
- `MAXIMIZE` remains strategic and outside target-gap state semantics;
- target unit is explicit;
- Reward Contract is explicit;
- reward basis is explicit;
- target band is valid;
- target lifecycle is separate from controller state and assessment;
- signed target-gap semantics match the frozen MINIMUM/BAND formulas;
- non-VALID assessment quality produces null/unavailable signed gap and performance state;
- NO_ACTIVE_TARGET requires no target identity and produces no target-seeking pressure;
- BELOW_TARGET + UNREACHABLE_SAFELY remains below-target but suppresses pursuit;
- controller produces no direct Action/Execution.


### Signed target-gap contract tests

For `MINIMUM`:

```text
target = 100, current = 92
    gap = +8
    state = BELOW_TARGET

target = 100, current = 100
    gap = 0
    state = WITHIN_TARGET_BAND

target = 100, current = 110
    gap = -10
    state = ABOVE_TARGET
```

For `BAND [95,105]`:

```text
current = 90
    gap = +5
    state = BELOW_TARGET

current = 101
    gap = 0
    state = WITHIN_TARGET_BAND

current = 110
    gap = -5
    state = ABOVE_TARGET
```

These are contract tests, not examples open to alternative interpretation.

### Time tests

Verify separation of:

- evaluation interval;
- statistical horizon;
- prediction horizon;
- pool accounting window;
- Reward Evaluation Window / Pool Time Block;
- outcome/reward attribution window;
- block interval.

### Noise tests

Verify target state does not thrash due to normal share/block variance.

### Safety tests

Verify target pursuit never bypasses hard safety, continuity, cooldown, or restart budget.

## 6. Outcome evaluation

For each Outcome evaluation define:

```text
outcome scope
Reward Evaluation Window
before/reference state
action/execution when applicable
observation window
baseline/reference window when attribution is claimed
expected effect when applicable
confounders
maturity condition
after/current state
realized metrics
attribution method/quality when applicable
```

A valid `PERFORMANCE_WINDOW` Outcome requires no Execution and supports shadow/no-action target tracking.

An `ACTION_ATTRIBUTED` Outcome may feed Learning/Promotion only when it declares an explicit reference basis such as a compatible baseline window or versioned no-action/reference expectation.

A post-action metric change is not automatically causal.

## 7. Reward evaluation

For each Reward Contract verify:

- mathematical formula;
- units/dimensional consistency;
- sign conventions;
- missing-data behavior;
- included realized cost semantics;
- pool payout semantics;
- stale/reject treatment;
- Reward Evaluation Window maturity/completeness;
- deterministic recomputation from mature Outcome;
- explicit exclusion of duplicated ADR-0006 probabilistic Risk/Uncertainty penalties;
- exploit/reward-hacking paths.

## 8. Reward-hacking checks

Challenge whether reward could improve while real objective worsens:

- raw hashrate up but accepted/effective work down;
- power down because useful work collapsed;
- short window captures transient spike;
- repeated switching captures local peaks but loses net reward;
- missing data suppresses penalties;
- restarts reset unfavorable windows;
- target is gamed by changing accounting basis.

## 9. Time-series/model validation

Hard rule:

```text
Never use naïve random train/test splitting for time-ordered telemetry and claim valid future performance.
```

Use as appropriate:

- chronological holdout;
- time-series split;
- walk-forward;
- rolling-origin evaluation;
- backtesting.

Check leakage, calibration, drift, and regime dependence.

## 10. Baselines

Every complex statistical/control method requires a meaningful baseline.

Examples:

- no-action;
- current stable profile;
- persistence forecast;
- rolling mean/median;
- EWMA;
- deterministic hysteresis controller.

Complexity must demonstrate measurable value.

## 11. Control evaluation

Measure at minimum:

### Safety
constraint violations, failed rollback, forbidden states.

### Stability
oscillation, chattering, overshoot, settling, action frequency.

### Economics
realized net effective reward, ActionCost, restart/switch cost.

### Robustness
stale/missing telemetry, delayed feedback, actuator failure, regime shift.

## 12. Reward target success

Success is not "hit the number once."

A target controller succeeds when, within accepted constraints:

- target state is correctly estimated;
- action is taken only when justified;
- target band is approached/maintained without unsafe churn;
- realized Reward improves over meaningful baseline where intervention occurs;
- stability and continuity remain acceptable;
- uncertainty is surfaced;
- unreachable targets are identified rather than chased.


## 13. Learning promotion verification

Learning must not self-promote.

Verify the complete path:

```text
LearningArtifact
→ UpdateProposal
→ Offline / Replay Verification
→ PromotionDecision
→ Active Version
```

Required checks:

- source Outcome/Reward/PredictionError evidence is mature;
- proposed change is versioned;
- replay/backtest does not use future leakage;
- regression/safety gates pass;
- rejection leaves active version unchanged;
- rollback to previous active version is defined where applicable.


## 14. M3 runtime-evidence persistence verification

Verify that:

```text
M2 DecisionEvaluationRepository
≠
M3 Runtime Evidence Persistence
```

and that M3 runtime persistence:

- preserves artifact identity/provenance/version;
- does not re-run cognition during reconstruction;
- does not repurpose frozen M2 fields;
- can round-trip RewardTarget lifecycle, RewardTargetControllerState, RewardTargetAssessment, target/window/outcome/reward/learning/promotion artifacts;
- keeps historical target and promotion decisions auditable.

## 15. Experiment record

Every experiment should identify:

```text
experiment_id
hypothesis
baseline
treatment
time range
target/reward contract version
model/controller version
input trace
acceptance criteria
stop condition
rollback
results
verification status
```

## 16. Reproducibility

Record applicable:

- source trace/dataset;
- code revision;
- config;
- versions;
- seeds;
- environment;
- commands;
- expected/actual outputs.

## 17. Promotion ladder

```text
architecture accepted
→ deterministic tests
→ simulation
→ replay
→ shadow
→ bounded live experiment
→ limited autonomous scope
→ broader autonomous scope
```

No stage is skipped solely because offline metrics are strong.
