# MiningGuardian M2 Final Baseline

## Milestone

**MiningGuardian M2 Final**

**Closure date:** 2026-09-19  
**Project package:** `mining-guardian`  
**Project version:** `0.1.0`  
**Declared Python requirement:** `>=3.12`  
**Release-finalization runtime Python:** `3.13.5`

## Final gate evidence

The exact Phase 12.3 baseline was locally verified during final closure.

| Gate | Command | Final status |
|---|---|---|
| Persistence model tests | `PYTHONPATH=src python -m pytest -q tests/unit/test_decision_persistence_models.py` | PASS — locally verified 26 tests |
| Persistence repository tests | `PYTHONPATH=src python -m pytest -q tests/unit/test_decision_persistence_repository.py` | PASS — locally verified 77 tests |
| Full pytest | `PYTHONPATH=src python -m pytest -q` | PASS — locally verified 480 tests |
| Ruff | `python -m ruff check src tests` | PASS — locally verified |
| Mypy | `python -m mypy src` | PASS — locally verified |
| Compileall | `python -m compileall -q src tests` | PASS — locally verified |

These gate results are final local verification evidence supplied for this exact baseline. Release-only finalization does not alter behavioral source or tests.

## Final architecture status

The accepted final pipeline is:

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

ADR-0006 remains:

```text
DUS = (Benefit × Confidence) - (Risk + ActionCost + Uncertainty)
```

No real action execution or observed-outcome learning is part of M2.

## Final persistence status

M2 persistence is bidirectionally complete:

```text
DecisionEvaluationArtifacts
→ save()
→ persisted evaluation graph
→ load_artifacts()
→ authoritative DecisionEvaluationArtifacts semantics
```

Persistence records and restores facts without rerunning candidate generation, policy evaluation, prediction, scoring, ranking, confidence calculation, or explanation generation.

### Timestamp authority

```text
DecisionEvaluationDB.timestamp_iso
= authoritative reconstruction source

DecisionEvaluationDB.timestamp
= convenience/query snapshot only
```

## Transaction/session contract

`DecisionEvaluationRepository.save()` requires a clean SQLAlchemy Session pending-state boundary.

One complete decision evaluation graph is committed atomically after all fallible validation/flush/ownership checks.

`load_artifacts()` is read-only.

## Key source/module inventory

### Decision domain/orchestration

```text
src/mining_guardian/agent/decision/models.py
src/mining_guardian/agent/decision/context.py
src/mining_guardian/agent/decision/candidates.py
src/mining_guardian/agent/decision/policies.py
src/mining_guardian/agent/decision/predictors.py
src/mining_guardian/agent/decision/scoring.py
src/mining_guardian/agent/decision/ranking.py
src/mining_guardian/agent/decision/confidence.py
src/mining_guardian/agent/decision/engine.py
src/mining_guardian/agent/decision/explanation.py
src/mining_guardian/agent/decision/lifecycle.py
```

### Persistence

```text
src/mining_guardian/storage/schema.py
src/mining_guardian/storage/database.py
src/mining_guardian/storage/decision_repository.py
src/mining_guardian/storage/repository.py
src/mining_guardian/storage/agent_repository.py
```

### Persistence acceptance tests

```text
tests/unit/test_decision_persistence_models.py
tests/unit/test_decision_persistence_repository.py
```

### Architecture/specification material

```text
ADR-0006_MiningGuardian_Decision_Engine_Implementation_Specification_FULL_v1.0.md
SPEC.md
SPECS.md
README.md
docs/
```

## Source-tree/package cleanliness rules

The final release archive includes source, tests, docs/specifications, project configuration, examples, and release/handoff documents.

It excludes local/runtime/generated noise such as:

```text
.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.pyc
*.pyo
mining_guardian.db
test_results.txt
dir run.txt
project_tree.txt
nested/old release archives
machine-specific editor state
```

## Accepted DB lifecycle limitation

SQLAlchemy `create_all()` does not alter an already-existing pre-`timestamp_iso` SQLite `decision_evaluations` table.

M2 includes no migration framework.

Existing older DB files therefore require recreation or an explicitly managed external migration before using the final schema.

This is an accepted M2 deployment limitation.

## Other accepted limitations

- named ZoneInfo identity, `datetime.fold`, and custom tzinfo identity are outside the current timestamp contract;
- observed decision outcomes are not persisted by M2;
- arbitrary candidate/ranking input tuple insertion order is not an independent persisted semantic;
- decision-evaluation save requires a clean pending-state Session.

## Freeze authority

The authoritative release freeze artifacts are:

```text
M2_FINAL_ACCEPTANCE.md
M3_ENGINEERING_HANDOFF.md
M2_FINAL_BASELINE.md
MiningGuardian_M2_FINAL.zip
```

No Git tag is required where Git history is unavailable or untrustworthy.

## Final readiness

**READY**

**A. M2 COMPLETE — FINAL BASELINE FROZEN AND READY FOR M3**
