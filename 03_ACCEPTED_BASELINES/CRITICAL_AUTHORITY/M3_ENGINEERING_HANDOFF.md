# MiningGuardian M3 Engineering Handoff

## 1. MiningGuardian mission

MiningGuardian is intended to evolve into an autonomous mining cognitive control system:

```text
observe
→ understand
→ predict
→ decide
→ eventually act safely
→ measure
→ learn
```

M2 establishes the evidence-driven decision and persistence foundation. It does **not** implement the eventual execution, observed-outcome learning, or adaptive-control portions.

## 2. What M2 delivered

M2 provides:

- evidence-driven decision architecture;
- explicit decision-domain contracts;
- candidate generation;
- policy boundary;
- prediction boundary;
- ADR-0006 scoring;
- deterministic ranking ownership;
- DecisionConfidenceResult;
- DecisionResult;
- structured DecisionExplanation;
- atomic decision-evaluation persistence;
- deterministic domain reconstruction;
- transaction/session integrity;
- authoritative timestamp fidelity.

## 3. Final M2 decision pipeline

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

Each stage has a deliberately bounded responsibility. Later work must not collapse these layers merely for convenience.

## 4. Domain artifact map

### CandidateAction

Represents one bounded proposed action. Important fields include domain candidate identity, ActionType, ExecutionCategory, description, expected gain, confidence, risk, transition cost, and reversibility.

`ExecutionCategory.FUTURE_CONTROL` is metadata only in M2.

### DecisionContext

Carries the decision-facing evidence/cognitive context assembled from existing world-state and working-memory artifacts. It is the bridge into candidate generation.

### PolicyResult

Records whether one candidate satisfies the policy boundary and preserves exact policy-violation identifiers.

Policy owns admissibility. Persistence does not reinterpret it.

### PredictionResult

Represents an estimated future result for one candidate, including confidence, uncertainty, horizon, optional expected changes, and optional rationale.

Prediction is not observed outcome.

### DecisionScore

Carries the already-computed ADR-0006 components and authoritative utility score.

Persistence never recomputes it.

### RankedCandidate

Associates a CandidateAction with its DecisionScore and supplied rank.

`DecisionRanker` owns rank production. Persistence stores/restores the supplied rank.

### DecisionConfidenceResult

Carries candidate identity, ordered evidence-confidence inputs, context/miner/hardware freshness, prediction reliability, nullable overall confidence, and limitations.

It is distinct from `DecisionResult.confidence`.

### DecisionResult

Carries decision identity/state, optional selected action, ordered alternatives, ordered rejected alternatives, decision-level numeric confidence, and result explanation string.

Its membership semantics are authoritative for selected/alternative/rejected persistence.

### DecisionExplanation

Structured Phase 11 explanation artifact. It is distinct from the `DecisionResult.explanation` string.

### DecisionEvaluationArtifacts

Frozen persistence handoff bundle containing the already-produced DecisionResult, candidates, policy/prediction/score/ranking artifacts, optional confidence, optional structured explanation, timestamp, and optional session ID.

It performs no cognition.

## 5. ADR-0006 scoring contract

The exact M2 Decision Utility Score is:

```text
DUS = (Benefit × Confidence) - (Risk + ActionCost + Uncertainty)
```

`DecisionScorer` owns this formula.

There are no hidden weights, bonuses, ML adjustments, or secondary utility formulas in M2.

Persistence and reconstruction must continue to preserve the supplied score, including unusual but valid values, rather than recalculating it.

## 6. Candidate / policy / prediction / ranking responsibilities

Candidate generation is evidence grounded:

```text
Evidence
→ Claim
→ Hypothesis
→ Candidate
```

Policy decides admissibility constraints only.

Prediction produces future estimates only.

Scoring calculates ADR-0006 utility.

Ranking owns ordering/rank production.

DecisionEngine orchestrates the pipeline.

Persistence records and reconstructs the resulting artifacts but does not reproduce any of these producer responsibilities.

## 7. Prediction is not outcome

M2 deliberately distinguishes `PredictionResult` from an observed/realized outcome.

There is no M2 decision-outcome persistence table and no realized reward/hashrate/power learning contract in the M2 decision-persistence boundary.

If M3 introduces observed outcomes or learning, it must do so explicitly rather than overloading PredictionResult.

## 8. DecisionResult confidence vs DecisionConfidenceResult

These are separate persisted facts.

`DecisionEvaluationDB.confidence` stores the exact supplied `DecisionResult.confidence`.

`DecisionConfidenceDB` stores the exact supplied Phase 9 confidence artifact, including prediction reliability and nullable overall confidence.

Persistence does not enforce the current DecisionEngine producer fallback relationship.

A confidence artifact may structurally reference any known candidate in the evaluation; persistence does not require it to be selected.

## 9. DecisionResult explanation vs DecisionExplanation

Keep three persistence concepts separate:

```text
DecisionResult.explanation
→ DecisionEvaluationDB.result_explanation

DecisionExplanation
→ DecisionExplanationDB.explanation_json

DecisionEvaluationDB.explanation_json
→ non-authoritative structured-explanation snapshot
```

`DecisionExplanationDB.explanation_json` is the authoritative structured explanation source for reconstruction.

Do not regenerate structured explanation during reads.

## 10. Persistence write contract

Public write boundary:

```text
DecisionEvaluationRepository.save(
    artifacts: DecisionEvaluationArtifacts
) -> DecisionEvaluationDB
```

The repository accepts already-produced artifacts only.

It validates structural identity/ownership/cardinality, persists one graph atomically, and commits once.

Transaction sequence:

```text
clean-session precondition
→ artifact validation
→ duplicate decision-id check
→ evaluation insert/flush
→ candidate insert/flush
→ child artifact inserts
→ final flush
→ persisted ownership validation
→ commit
→ return existing ORM object
```

Failures before successful commit roll back the repository-owned transaction.

The repository does not rerun producer components.

## 11. Persistence reconstruction contract

Public read-side domain boundary:

```text
DecisionEvaluationRepository.load_artifacts(
    decision_id: str
) -> DecisionEvaluationArtifacts | None
```

`get_by_decision_id()` remains ORM graph retrieval only.

`load_artifacts()` reconstructs domain artifacts solely from persisted state.

It does not add, delete, flush, commit, or rollback and does not invoke producer engines.

DecisionResult membership comes from explicit `result_role` / `result_position`, not ranking or policy.

Ranking restores exact persisted rank values and does not require contiguous ranks or selected rank 1.

## 12. Timestamp authority

The authoritative rule is:

```text
DecisionEvaluationDB.timestamp_iso
= authoritative reconstruction source

DecisionEvaluationDB.timestamp
= convenience/query snapshot
```

Write-side serialization is derived directly from `DecisionEvaluationArtifacts.timestamp`.

Read-side reconstruction parses `timestamp_iso`; it must not fall back to the lossy SQLite DateTime snapshot.

Current supported semantics cover naive/aware distinction, wall-clock value, microseconds, and UTC/fixed offsets.

## 13. Clean-session repository rule

`DecisionEvaluationRepository.save()` requires that the injected SQLAlchemy Session begin with no unrelated pending `new`, `dirty`, or `deleted` state.

This prevents the repository's commit/rollback ownership from silently committing or discarding caller-owned pending work.

Do not remove this precondition casually.

## 14. No-execution boundary

M2 decides and records; it does not execute.

There is no real GPU clock/voltage/fan/power control, miner lifecycle control, pool switch, algorithm switch, wallet mutation, or selected-action executor in the M2 decision architecture.

`FUTURE_CONTROL` remains metadata only.

Any M3 execution authority must be introduced explicitly with new architecture and safety contracts.

## 15. Accepted limitations

1. Pre-`timestamp_iso` SQLite files are not automatically upgraded by `create_all()`.
2. M2 has no migration framework.
3. Named ZoneInfo identity, `datetime.fold`, and custom tzinfo identity are outside the timestamp contract.
4. M2 persistence does not persist observed decision outcomes.
5. Arbitrary candidate/ranking transport tuple insertion order is not an independent persisted semantic.
6. `DecisionEvaluationRepository.save()` requires a clean pending-state Session.

## 16. What M3 may build on top of

M3 may use the existing evidence/cognitive foundation, DecisionContext, candidate/policy/prediction/scoring/ranking/confidence/explanation contracts, and the complete persistence read/write boundary as stable inputs to new explicitly approved runtime intelligence.

M3 may add new architecture around observed outcomes, learning, simulation, validation, execution safety, or control only through deliberate design and ADRs.

## 17. What M3 must not silently rewrite

Unless a future explicit ADR intentionally supersedes the contract, M3 must not silently replace:

- ADR-0006;
- evidence → claim → hypothesis → candidate semantics;
- policy ownership;
- prediction boundary;
- ranking ownership;
- confidence semantics;
- DecisionResult versus DecisionConfidenceResult distinction;
- DecisionResult.explanation versus DecisionExplanation separation;
- persistence transaction boundaries;
- clean-session rule;
- `timestamp_iso` authority;
- prediction/outcome separation;
- M2 no-execution boundary.

## 18. Recommended first M3 action

Before introducing new runtime intelligence, read:

- the current ADRs;
- `SPEC.md` / `SPECS.md`;
- current domain contracts;
- `M2_FINAL_ACCEPTANCE.md`;
- `M2_FINAL_BASELINE.md`;
- this handoff.

Then begin the separate M3 architecture/knowledge-pack process.

This handoff intentionally does **not** choose PID, MPC, bandits, ML models, reward-learning strategies, or execution/control architecture.
