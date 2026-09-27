# MiningGuardian M2 Final Acceptance

**Milestone:** MiningGuardian M2 Final  
**Closure date:** 2026-09-19  
**Project version:** 0.1.0

## Completed M2 scope

M2 establishes MiningGuardian's evidence-driven decision architecture and its lossless persistence boundary. The completed decision pipeline is:

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

M2 delivers explicit domain contracts, bounded candidate generation, policy validation, prediction artifacts, ADR-0006 decision scoring, deterministic ranking ownership, decision-confidence artifacts, DecisionResult, structured DecisionExplanation, atomic persistence, and deterministic reconstruction.

## Durable M2 invariants

### Evidence-grounded candidates

Candidate generation remains:

```text
Evidence
→ Claim
→ Hypothesis
→ Candidate
```

Candidate generation does not bypass the cognitive evidence foundation with an independent raw-telemetry decision path.

### ADR-0006 scoring

The approved Decision Utility Score is:

```text
DUS = (Benefit × Confidence) - (Risk + ActionCost + Uncertainty)
```

There are no hidden weights, bonuses, ML adjustments, secondary utility formulas, or persistence-side score recomputations.

`DecisionScorer` owns score calculation. Persistence records and reconstructs the supplied `DecisionScore` exactly.

### Ranking ownership

`DecisionRanker` owns ranking behavior.

Persistence stores supplied ranking values and reconstruction restores them. Persistence does not require contiguous ranks, selected candidate rank 1, ranking order to equal DecisionResult order, or ranking membership to equal selected + alternatives.

### Prediction is not observed outcome

`PredictionResult` is a future estimate. M2 does not persist observed decision outcomes, realized reward, realized hashrate, or realized power, and it does not implement outcome-learning behavior.

### Confidence separation

`DecisionResult.confidence` and `DecisionConfidenceResult` are distinct artifacts.

Persistence records them independently. It does not enforce DecisionEngine's current producer fallback relationship, and it does not require the confidence artifact's candidate to equal the selected candidate.

### Explanation separation

`DecisionResult.explanation` is the Phase 10 result-explanation string.

`DecisionExplanation` is the structured Phase 11 explanation artifact.

They remain distinct in persistence. `DecisionExplanationDB.explanation_json` is authoritative for structured explanation reconstruction.

### No execution in M2

`ExecutionCategory.FUTURE_CONTROL` remains metadata only.

M2 does not execute selected actions and does not perform GPU tuning, miner control, pool switching, algorithm switching, wallet changes, or runtime automation.

## Persistence status

M2 persistence is bidirectionally complete:

```text
DecisionEvaluationArtifacts
→ DecisionEvaluationRepository.save(...)
→ persistence graph
→ DecisionEvaluationRepository.load_artifacts(...)
→ authoritative DecisionEvaluationArtifacts semantics
```

Persistence is **record + restore**, not **record + decide again**.

Write-side persistence validates identity, ownership, cardinality, referential integrity, and transaction atomicity without rerunning decision components.

Read-side reconstruction restores persisted facts and performs structural-integrity validation without invoking DecisionEngine, CandidateGenerator, DecisionPolicy, OutcomePredictor, DecisionScorer, DecisionRanker, DecisionConfidenceEngine, or DecisionExplainer.

### Transaction boundary

`DecisionEvaluationRepository.save()` requires a clean SQLAlchemy Session pending-state boundary before it starts repository-owned work.

The write transaction follows:

```text
clean-session precondition
→ validation
→ root insert/flush
→ candidate insert/flush
→ child artifacts
→ final flush
→ persisted ownership validation
→ commit
→ return existing ORM object
```

There is no fallible repository reload after successful commit.

### Timestamp authority

```text
DecisionEvaluationDB.timestamp_iso
= authoritative reconstruction source

DecisionEvaluationDB.timestamp
= convenience/query snapshot only
```

The authoritative ISO representation preserves MiningGuardian's supported timestamp semantics: naive versus aware, wall-clock value, microseconds, and explicit UTC/fixed offset.

## Final quality gates

The exact Phase 12.3 baseline was locally verified during final closure with:

```text
Focused persistence-model pytest:      PASS (26 tests)
Focused persistence-repository pytest: PASS (77 tests)
Full pytest:                            PASS (480 tests)
Ruff:                                   PASS
Mypy:                                   PASS
compileall:                             PASS
```

Commands:

```bash
PYTHONPATH=src python -m pytest -q tests/unit/test_decision_persistence_models.py
PYTHONPATH=src python -m pytest -q tests/unit/test_decision_persistence_repository.py
PYTHONPATH=src python -m pytest -q
python -m ruff check src tests
python -m mypy src
python -m compileall -q src tests
```

No source, test, schema, domain, or runtime-configuration changes were required to obtain these passes.

## Accepted M2 limitations

These are accepted limitations, not release blockers:

1. SQLite databases created before `timestamp_iso` are not automatically upgraded by SQLAlchemy `create_all()`.
2. M2 does not include a migration framework.
3. Named `ZoneInfo` identity, `datetime.fold`, and custom `tzinfo` identity are outside the current timestamp contract.
4. Persistence stores/reconstructs decision artifacts but does not persist observed decision outcomes.
5. Arbitrary candidate/ranking input tuple insertion order is not an independent persisted semantic.
6. `DecisionEvaluationRepository.save()` requires a clean pending-state SQLAlchemy Session.

## M3 boundary

M3 may build on M2, but must not silently replace the following without an explicit superseding ADR:

- ADR-0006 scoring;
- evidence → claim → hypothesis → candidate semantics;
- policy ownership;
- prediction boundary;
- ranking ownership;
- confidence semantics;
- DecisionResult/DecisionExplanation separation;
- persistence transaction boundaries;
- `timestamp_iso` authority;
- prediction/outcome separation;
- M2's no-execution boundary.

Runtime intelligence, observed-outcome evaluation/learning, and any future execution/control authority belong to future architecture work.

## Final readiness

All required M2 implementation and final acceptance gates are complete for the verified baseline.

**M2 FINAL ACCEPTANCE: READY**

**A. M2 COMPLETE — FINAL BASELINE FROZEN AND READY FOR M3**
