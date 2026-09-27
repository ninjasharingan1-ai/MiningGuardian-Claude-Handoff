import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from mining_guardian.agent.cognition.enums import Reliability
from mining_guardian.agent.decision.confidence import (
    ConfidenceLimitation,
    DecisionConfidenceResult,
    EvidenceConfidenceInput,
)
from mining_guardian.agent.decision.explanation import (
    CandidateExplanation,
    DecisionExplanation,
    ExplanationLimitation,
    RejectedCandidateExplanation,
)
from mining_guardian.agent.decision.models import (
    ActionType,
    CandidateAction,
    DecisionResult,
    ExecutionCategory,
)
from mining_guardian.agent.decision.policies import PolicyResult
from mining_guardian.agent.decision.predictors import PredictionHorizon, PredictionResult
from mining_guardian.agent.decision.ranking import RankedCandidate
from mining_guardian.agent.decision.scoring import DecisionScore
from mining_guardian.agent.temporal import FreshnessLevel
from mining_guardian.storage.database import Database
from mining_guardian.storage.decision_repository import (
    DecisionEvaluationArtifacts,
    DecisionEvaluationRepository,
    DecisionPersistenceIntegrityError,
)
from mining_guardian.storage.schema import (
    AlgorithmDB,
    Base,
    DecisionCandidateDB,
    DecisionConfidenceDB,
    DecisionEvaluationDB,
    DecisionExplanationDB,
    DecisionPolicyResultDB,
    DecisionPredictionDB,
    DecisionRankingDB,
    DecisionScoreDB,
    SessionDB,
)


@pytest.fixture
def database() -> Database:
    db = Database("sqlite:///:memory:")
    yield db
    db.close()


@pytest.fixture
def session(database: Database) -> Session:
    db_session = database.SessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()


def _candidate(
    candidate_id: str,
    *,
    action_type: ActionType = ActionType.EVALUATE_EFFICIENCY,
    expected_gain: float = 1.0,
    confidence: float = 0.8,
    risk_score: float = 0.1,
    transition_cost: float = 0.2,
) -> CandidateAction:
    return CandidateAction(
        id=candidate_id,
        action_type=action_type,
        description=f"candidate {candidate_id}",
        execution_category=ExecutionCategory.OBSERVATION_ONLY,
        expected_gain=expected_gain,
        confidence=confidence,
        risk_score=risk_score,
        transition_cost=transition_cost,
        reversible=True,
    )


def _prediction(
    candidate_id: str,
    *,
    rationale: str | None = "preserved rationale",
    confidence: float = 0.67,
) -> PredictionResult:
    return PredictionResult(
        candidate_id=candidate_id,
        expected_reward_change=1.25,
        expected_hashrate_change=None,
        expected_power_change=-3.5,
        confidence=confidence,
        uncertainty=0.15,
        horizon=PredictionHorizon.SHORT_TERM,
        rationale=rationale,
    )


def _score(candidate_id: str, *, utility_score: float) -> DecisionScore:
    return DecisionScore(
        candidate_id=candidate_id,
        benefit=1.25,
        confidence=0.67,
        risk=0.1,
        action_cost=0.2,
        uncertainty=0.15,
        utility_score=utility_score,
    )


def _confidence(
    candidate_id: str,
    *,
    prediction_reliability: float = 0.67,
    overall_confidence: float | None = None,
) -> DecisionConfidenceResult:
    return DecisionConfidenceResult(
        candidate_id=candidate_id,
        evidence_inputs=[
            EvidenceConfidenceInput(
                evidence_id="evidence-a",
                reliability=Reliability.HIGH,
                freshness=FreshnessLevel.FRESH,
            ),
            EvidenceConfidenceInput(
                evidence_id="evidence-b",
                reliability=Reliability.MEDIUM,
                freshness=FreshnessLevel.RECENT,
            ),
        ],
        context_freshness=FreshnessLevel.RECENT,
        miner_freshness=FreshnessLevel.FRESH,
        hardware_freshness=FreshnessLevel.STALE,
        prediction_reliability=prediction_reliability,
        overall_confidence=overall_confidence,
        limitations=[
            ConfidenceLimitation.NUMERIC_EVIDENCE_QUALITY_UNAVAILABLE,
            ConfidenceLimitation.NUMERIC_FRESHNESS_FACTOR_UNAVAILABLE,
        ],
    )


def _explanation(
    result: DecisionResult,
    confidence: DecisionConfidenceResult | None = None,
) -> DecisionExplanation:
    selected = (
        CandidateExplanation(
            rank=1,
            candidate=result.selected_action,
            score=None,
            reason="highest_ranked_eligible_candidate",
        )
        if result.selected_action is not None
        else None
    )
    alternatives = [
        CandidateExplanation(
            rank=index + 2,
            candidate=candidate,
            score=None,
            reason=None,
        )
        for index, candidate in enumerate(result.alternatives)
    ]
    rejected = [
        RejectedCandidateExplanation(
            candidate=candidate,
            policy_violations=[],
            limitations=[ExplanationLimitation.REJECTION_REASON_UNAVAILABLE],
        )
        for candidate in result.rejected_alternatives
    ]
    return DecisionExplanation(
        decision_id=result.decision_id,
        decision_state=result.state,
        selected=selected,
        alternatives=alternatives,
        rejected_alternatives=rejected,
        confidence=confidence,
        limitations=[],
    )


def _artifacts(
    *,
    decision_id: str = "decision-1",
    selected: CandidateAction | None = None,
    alternatives: tuple[CandidateAction, ...] = (),
    rejected: tuple[CandidateAction, ...] = (),
    candidates: tuple[CandidateAction, ...] | None = None,
    policy_results: dict[str, PolicyResult] | None = None,
    predictions: dict[str, PredictionResult] | None = None,
    scores: dict[str, DecisionScore] | None = None,
    ranking: tuple[RankedCandidate, ...] = (),
    confidence: DecisionConfidenceResult | None = None,
    explanation: DecisionExplanation | None = None,
    result_confidence: float | None = None,
    timestamp: datetime | None = None,
    session_id: str | None = None,
    auto_select: bool = True,
) -> DecisionEvaluationArtifacts:
    if auto_select and selected is None and not alternatives and not rejected:
        selected = _candidate("selected")

    supplied_candidates = candidates
    if supplied_candidates is None:
        members: list[CandidateAction] = []
        if selected is not None:
            members.append(selected)
        members.extend(alternatives)
        members.extend(rejected)
        supplied_candidates = tuple(members)

    if result_confidence is None:
        if confidence is not None:
            result_confidence = (
                confidence.overall_confidence
                if confidence.overall_confidence is not None
                else confidence.prediction_reliability
            )
        else:
            result_confidence = 0.0

    result = DecisionResult(
        decision_id=decision_id,
        state="approved",
        selected_action=selected,
        alternatives=list(alternatives),
        rejected_alternatives=list(rejected),
        confidence=result_confidence,
        explanation=f"result explanation for {decision_id}",
    )
    return DecisionEvaluationArtifacts(
        timestamp=timestamp or datetime(2026, 9, 19, 1, 2, 3),
        session_id=session_id,
        result=result,
        candidates=supplied_candidates,
        policy_results=policy_results or {},
        predictions=predictions or {},
        scores=scores or {},
        ranking=ranking,
        confidence=confidence,
        explanation=explanation,
    )


def _candidate_rows(row: DecisionEvaluationDB) -> dict[str, DecisionCandidateDB]:
    return {candidate.candidate_id: candidate for candidate in row.candidates}


def test_persist_minimal_valid_evaluation(session: Session):
    artifacts = _artifacts()

    row = DecisionEvaluationRepository(session).save(artifacts)

    assert row.decision_id == artifacts.result.decision_id
    assert row.state == artifacts.result.state
    assert row.confidence == artifacts.result.confidence
    assert row.result_explanation == artifacts.result.explanation
    assert len(row.candidates) == 1


@pytest.mark.parametrize(
    "timestamp",
    [
        datetime(2026, 9, 19, 1, 2, 3, 456789),
        datetime(2026, 9, 19, 1, 2, 3, 456789, tzinfo=UTC),
        datetime(
            2026,
            9,
            19,
            1,
            2,
            3,
            456789,
            tzinfo=timezone(timedelta(hours=3)),
        ),
        datetime(
            2026,
            9,
            19,
            1,
            2,
            3,
            456789,
            tzinfo=timezone(-timedelta(hours=5, minutes=30)),
        ),
        datetime(2026, 9, 19, 1, 2, 3, tzinfo=UTC),
    ],
)
def test_authoritative_timestamp_iso_preserves_supported_timestamp_semantics(
    session: Session,
    timestamp: datetime,
):
    artifacts = _artifacts(
        decision_id=f"decision-timestamp-{timestamp.isoformat()}",
        timestamp=timestamp,
    )

    row = DecisionEvaluationRepository(session).save(artifacts)

    expected = timestamp.isoformat(timespec="microseconds")
    assert row.timestamp_iso == expected

    reconstructed = datetime.fromisoformat(row.timestamp_iso)
    assert reconstructed == timestamp
    assert reconstructed.microsecond == timestamp.microsecond
    assert (reconstructed.tzinfo is None) is (timestamp.tzinfo is None)
    assert reconstructed.utcoffset() == timestamp.utcoffset()


def test_authoritative_timestamp_distinguishes_meaningful_timestamp_semantics(
    session: Session,
):
    wall_clock = datetime(2026, 9, 19, 1, 2, 3, 456789)
    utc_aware = wall_clock.replace(tzinfo=UTC)
    positive_offset = wall_clock.replace(tzinfo=timezone(timedelta(hours=3)))

    naive_row = DecisionEvaluationRepository(session).save(
        _artifacts(decision_id="decision-timestamp-naive", timestamp=wall_clock)
    )
    utc_row = DecisionEvaluationRepository(session).save(
        _artifacts(decision_id="decision-timestamp-utc", timestamp=utc_aware)
    )
    offset_row = DecisionEvaluationRepository(session).save(
        _artifacts(decision_id="decision-timestamp-offset", timestamp=positive_offset)
    )

    assert len({naive_row.timestamp_iso, utc_row.timestamp_iso, offset_row.timestamp_iso}) == 3


def test_datetime_snapshot_is_not_authoritative_for_offset_aware_timestamp(
    session: Session,
):
    supplied = datetime(
        2026,
        9,
        19,
        1,
        2,
        3,
        456789,
        tzinfo=timezone(timedelta(hours=3)),
    )
    repository = DecisionEvaluationRepository(session)
    repository.save(
        _artifacts(decision_id="decision-timestamp-snapshot", timestamp=supplied)
    )

    session.expunge_all()
    reloaded = repository.get_by_decision_id("decision-timestamp-snapshot")

    assert reloaded is not None
    assert reloaded.timestamp.tzinfo is None
    assert reloaded.timestamp_iso == supplied.isoformat(timespec="microseconds")
    assert datetime.fromisoformat(reloaded.timestamp_iso) == supplied


def test_malformed_authoritative_timestamp_is_rejected_by_intended_parser():
    with pytest.raises(ValueError):
        datetime.fromisoformat("not-a-valid-decision-timestamp")


def test_selected_candidate_uses_persisted_candidate_row_identity(session: Session):
    selected = _candidate("selected-row")

    row = DecisionEvaluationRepository(session).save(
        _artifacts(selected=selected, decision_id="decision-selected-row")
    )
    candidate = _candidate_rows(row)[selected.id]

    assert row.selected_candidate_id == candidate.id
    assert row.selected_candidate_id != selected.id
    assert row.selected_candidate.candidate_id == selected.id


@pytest.mark.parametrize(
    ("role", "selected", "alternatives", "rejected"),
    [
        (
            "selected",
            _candidate("no-action-selected", action_type=ActionType.NO_ACTION),
            (),
            (),
        ),
        (
            "alternative",
            _candidate("selected-for-no-action-alt"),
            (_candidate("no-action-alt", action_type=ActionType.NO_ACTION),),
            (),
        ),
        (
            "rejected",
            _candidate("selected-for-no-action-rejected"),
            (),
            (_candidate("no-action-rejected", action_type=ActionType.NO_ACTION),),
        ),
    ],
)
def test_no_action_persists_without_special_treatment(
    session: Session,
    role: str,
    selected: CandidateAction,
    alternatives: tuple[CandidateAction, ...],
    rejected: tuple[CandidateAction, ...],
):
    all_candidates = (selected, *alternatives, *rejected)
    row = DecisionEvaluationRepository(session).save(
        _artifacts(
            decision_id=f"decision-no-action-{role}",
            selected=selected,
            alternatives=alternatives,
            rejected=rejected,
            candidates=all_candidates,
        )
    )

    no_action = next(
        candidate
        for candidate in row.candidates
        if candidate.action_type == ActionType.NO_ACTION.value
    )
    assert no_action.result_role == role


def test_alternative_and_rejected_order_are_preserved_exactly(session: Session):
    selected = _candidate("selected")
    alternatives = (_candidate("alt-b"), _candidate("alt-a"))
    rejected = (_candidate("reject-c"), _candidate("reject-a"), _candidate("reject-b"))

    row = DecisionEvaluationRepository(session).save(
        _artifacts(
            decision_id="decision-membership-order",
            selected=selected,
            alternatives=alternatives,
            rejected=rejected,
        )
    )

    alternative_rows = sorted(
        (candidate for candidate in row.candidates if candidate.result_role == "alternative"),
        key=lambda candidate: candidate.result_position,
    )
    rejected_rows = sorted(
        (candidate for candidate in row.candidates if candidate.result_role == "rejected"),
        key=lambda candidate: candidate.result_position,
    )
    assert [candidate.candidate_id for candidate in alternative_rows] == [
        "alt-b",
        "alt-a",
    ]
    assert [candidate.result_position for candidate in alternative_rows] == [0, 1]
    assert [candidate.candidate_id for candidate in rejected_rows] == [
        "reject-c",
        "reject-a",
        "reject-b",
    ]
    assert [candidate.result_position for candidate in rejected_rows] == [0, 1, 2]


def test_policy_result_and_exact_violations_are_preserved(session: Session):
    selected = _candidate("policy-candidate")
    policy = PolicyResult(
        allowed=False,
        violations=["confidence_below_minimum", "required_evidence_missing"],
    )

    row = DecisionEvaluationRepository(session).save(
        _artifacts(
            decision_id="decision-policy",
            selected=selected,
            policy_results={selected.id: policy},
        )
    )
    stored = _candidate_rows(row)[selected.id].policy_result

    assert stored is not None
    assert stored.allowed is False
    assert json.loads(stored.violations_json) == policy.violations


@pytest.mark.parametrize("rationale", ["preserved rationale", None])
def test_prediction_is_preserved_including_nullable_rationale(
    session: Session,
    rationale: str | None,
):
    selected = _candidate("prediction-candidate")
    prediction = _prediction(selected.id, rationale=rationale)

    row = DecisionEvaluationRepository(session).save(
        _artifacts(
            decision_id=f"decision-prediction-{rationale is None}",
            selected=selected,
            predictions={selected.id: prediction},
        )
    )
    stored = _candidate_rows(row)[selected.id].prediction

    assert stored is not None
    assert stored.expected_reward_change == prediction.expected_reward_change
    assert stored.expected_hashrate_change == prediction.expected_hashrate_change
    assert stored.expected_power_change == prediction.expected_power_change
    assert stored.confidence == prediction.confidence
    assert stored.uncertainty == prediction.uncertainty
    assert stored.horizon == prediction.horizon.value
    assert stored.rationale == rationale
    assert "actual_reward" not in inspect(DecisionPredictionDB).columns
    assert "actual_hashrate" not in inspect(DecisionPredictionDB).columns
    assert "actual_power" not in inspect(DecisionPredictionDB).columns
    assert "decision_outcomes" not in Base.metadata.tables


def test_score_is_stored_exactly_without_recalculation(session: Session):
    selected = _candidate("score-candidate")
    score = _score(selected.id, utility_score=98.75)

    row = DecisionEvaluationRepository(session).save(
        _artifacts(
            decision_id="decision-score",
            selected=selected,
            scores={selected.id: score},
        )
    )
    stored = _candidate_rows(row)[selected.id].score

    assert stored is not None
    assert stored.benefit == score.benefit
    assert stored.confidence == score.confidence
    assert stored.risk == score.risk
    assert stored.action_cost == score.action_cost
    assert stored.uncertainty == score.uncertainty
    assert stored.utility_score == 98.75


def test_ranking_positions_are_preserved_without_score_sorting(session: Session):
    selected = _candidate("rank-low")
    alternative = _candidate("rank-high")
    selected_score = _score(selected.id, utility_score=-50.0)
    alternative_score = _score(alternative.id, utility_score=500.0)
    ranking = (
        RankedCandidate(rank=1, candidate=selected, score=selected_score),
        RankedCandidate(rank=2, candidate=alternative, score=alternative_score),
    )

    row = DecisionEvaluationRepository(session).save(
        _artifacts(
            decision_id="decision-ranking",
            selected=selected,
            alternatives=(alternative,),
            scores={
                selected.id: selected_score,
                alternative.id: alternative_score,
            },
            ranking=ranking,
        )
    )

    stored_ranking = sorted(row.rankings, key=lambda item: item.rank_position)
    stored_candidates = _candidate_rows(row)
    assert [
        next(
            candidate_id
            for candidate_id, candidate in stored_candidates.items()
            if candidate.id == ranked.candidate_id
        )
        for ranked in stored_ranking
    ] == [selected.id, alternative.id]
    assert [ranked.rank_position for ranked in stored_ranking] == [1, 2]


def test_non_contiguous_ranking_positions_are_preserved(session: Session):
    selected = _candidate("rank-gap-a")
    alternative = _candidate("rank-gap-b")
    score_a = _score(selected.id, utility_score=5.0)
    score_b = _score(alternative.id, utility_score=4.0)
    ranking = (
        RankedCandidate(rank=1, candidate=selected, score=score_a),
        RankedCandidate(rank=3, candidate=alternative, score=score_b),
    )

    row = DecisionEvaluationRepository(session).save(
        _artifacts(
            decision_id="decision-ranking-gap",
            selected=selected,
            alternatives=(alternative,),
            scores={selected.id: score_a, alternative.id: score_b},
            ranking=ranking,
        )
    )

    assert sorted(item.rank_position for item in row.rankings) == [1, 3]


def test_ranking_order_is_independent_from_decision_result_order(session: Session):
    selected = _candidate("rank-order-selected")
    alternative = _candidate("rank-order-alternative")
    score_selected = _score(selected.id, utility_score=5.0)
    score_alternative = _score(alternative.id, utility_score=4.0)
    ranking = (
        RankedCandidate(rank=1, candidate=alternative, score=score_alternative),
        RankedCandidate(rank=4, candidate=selected, score=score_selected),
    )

    row = DecisionEvaluationRepository(session).save(
        _artifacts(
            decision_id="decision-ranking-independent-order",
            selected=selected,
            alternatives=(alternative,),
            scores={
                selected.id: score_selected,
                alternative.id: score_alternative,
            },
            ranking=ranking,
        )
    )
    rows = _candidate_rows(row)
    rank_by_candidate_row_id = {
        item.candidate_id: item.rank_position for item in row.rankings
    }

    assert rows[selected.id].result_role == "selected"
    assert rows[alternative.id].result_role == "alternative"
    assert rows[alternative.id].result_position == 0
    assert rank_by_candidate_row_id[rows[alternative.id].id] == 1
    assert rank_by_candidate_row_id[rows[selected.id].id] == 4


def test_ranking_set_may_include_rejected_candidate_independently(session: Session):
    selected = _candidate("rank-set-selected")
    alternative = _candidate("rank-set-alternative")
    rejected = _candidate("rank-set-rejected")
    rejected_score = _score(rejected.id, utility_score=-10.0)

    row = DecisionEvaluationRepository(session).save(
        _artifacts(
            decision_id="decision-ranking-independent-set",
            selected=selected,
            alternatives=(alternative,),
            rejected=(rejected,),
            scores={rejected.id: rejected_score},
            ranking=(
                RankedCandidate(
                    rank=7,
                    candidate=rejected,
                    score=rejected_score,
                ),
            ),
        )
    )
    rows = _candidate_rows(row)

    assert rows[rejected.id].result_role == "rejected"
    assert len(row.rankings) == 1
    assert row.rankings[0].candidate_id == rows[rejected.id].id
    assert row.rankings[0].rank_position == 7


def test_confidence_artifact_preserves_every_component_and_null_aggregate(session: Session):
    selected = _candidate("confidence-candidate")
    confidence = _confidence(selected.id, overall_confidence=None)

    row = DecisionEvaluationRepository(session).save(
        _artifacts(
            decision_id="decision-confidence-null",
            selected=selected,
            confidence=confidence,
            result_confidence=confidence.prediction_reliability,
        )
    )
    stored = row.confidence_artifact

    assert stored is not None
    assert stored.candidate_id == row.selected_candidate_id
    assert json.loads(stored.evidence_inputs_json) == [
        {
            "evidence_id": "evidence-a",
            "reliability": "high",
            "freshness": "fresh",
        },
        {
            "evidence_id": "evidence-b",
            "reliability": "medium",
            "freshness": "recent",
        },
    ]
    assert stored.context_freshness == "recent"
    assert stored.miner_freshness == "fresh"
    assert stored.hardware_freshness == "stale"
    assert stored.prediction_reliability == 0.67
    assert stored.overall_confidence is None
    assert json.loads(stored.limitations_json) == [
        "numeric_evidence_quality_unavailable",
        "numeric_freshness_factor_unavailable",
    ]
    assert row.confidence == 0.67


@pytest.mark.parametrize(
    ("overall_confidence", "result_confidence"),
    [
        (None, 0.25),
        (0.90, 0.25),
    ],
)
def test_confidence_values_are_persisted_independently(
    session: Session,
    overall_confidence: float | None,
    result_confidence: float,
):
    selected = _candidate("confidence-independent")
    confidence = _confidence(
        selected.id,
        prediction_reliability=0.70,
        overall_confidence=overall_confidence,
    )

    row = DecisionEvaluationRepository(session).save(
        _artifacts(
            decision_id=f"decision-confidence-independent-{overall_confidence}",
            selected=selected,
            confidence=confidence,
            result_confidence=result_confidence,
        )
    )

    assert row.confidence == result_confidence
    assert row.confidence_artifact is not None
    assert row.confidence_artifact.prediction_reliability == 0.70
    assert row.confidence_artifact.overall_confidence == overall_confidence


def test_no_selection_with_rejected_candidate_persists(session: Session):
    rejected = _candidate("no-selection-rejected")

    row = DecisionEvaluationRepository(session).save(
        _artifacts(
            decision_id="decision-no-selection-rejected",
            selected=None,
            rejected=(rejected,),
            candidates=(rejected,),
            auto_select=False,
        )
    )
    rejected_row = _candidate_rows(row)[rejected.id]

    assert row.selected_candidate_id is None
    assert rejected_row.result_role == "rejected"
    assert rejected_row.result_position == 0


def test_no_selection_with_no_candidates_persists(session: Session):
    row = DecisionEvaluationRepository(session).save(
        _artifacts(
            decision_id="decision-no-selection-empty",
            selected=None,
            candidates=(),
            auto_select=False,
        )
    )

    assert row.selected_candidate_id is None
    assert row.candidates == []


def test_no_selection_may_persist_confidence_for_known_candidate(session: Session):
    candidate = _candidate("no-selection-confidence")
    confidence = _confidence(
        candidate.id,
        prediction_reliability=0.70,
        overall_confidence=0.90,
    )

    row = DecisionEvaluationRepository(session).save(
        _artifacts(
            decision_id="decision-no-selection-confidence",
            selected=None,
            rejected=(candidate,),
            candidates=(candidate,),
            confidence=confidence,
            result_confidence=0.25,
            auto_select=False,
        )
    )
    candidate_row = _candidate_rows(row)[candidate.id]

    assert row.selected_candidate_id is None
    assert row.confidence == 0.25
    assert row.confidence_artifact is not None
    assert row.confidence_artifact.candidate_id == candidate_row.id
    assert row.confidence_artifact.prediction_reliability == 0.70
    assert row.confidence_artifact.overall_confidence == 0.90


def test_result_and_structured_explanations_remain_distinct(session: Session):
    selected = _candidate("explanation-candidate")
    confidence = _confidence(selected.id)
    base = _artifacts(
        decision_id="decision-explanation",
        selected=selected,
        confidence=confidence,
    )
    explanation = _explanation(base.result, confidence)
    artifacts = base.model_copy(update={"explanation": explanation})

    row = DecisionEvaluationRepository(session).save(artifacts)

    assert row.result_explanation == base.result.explanation
    assert row.explanation_json == explanation.model_dump_json()
    assert row.explanation is not None
    assert row.explanation.explanation_json == explanation.model_dump_json()
    assert row.result_explanation != row.explanation.explanation_json


def test_unknown_selected_candidate_is_rejected(session: Session):
    supplied = _candidate("supplied")
    unknown = _candidate("unknown")

    with pytest.raises(DecisionPersistenceIntegrityError, match="unknown candidate"):
        DecisionEvaluationRepository(session).save(
            _artifacts(
                decision_id="decision-unknown-selected",
                selected=unknown,
                candidates=(supplied,),
            )
        )


def test_duplicate_candidate_domain_id_is_rejected(session: Session):
    first = _candidate("duplicate")
    second = first.model_copy(update={"description": "different"})

    with pytest.raises(DecisionPersistenceIntegrityError, match="duplicate candidate"):
        DecisionEvaluationRepository(session).save(
            _artifacts(
                decision_id="decision-duplicate-candidate",
                selected=first,
                candidates=(first, second),
            )
        )


def test_candidate_role_overlap_is_rejected(session: Session):
    candidate = _candidate("overlap")

    with pytest.raises(DecisionPersistenceIntegrityError, match="multiple DecisionResult roles"):
        DecisionEvaluationRepository(session).save(
            _artifacts(
                decision_id="decision-role-overlap",
                selected=candidate,
                alternatives=(candidate,),
                candidates=(candidate,),
            )
        )


def test_incomplete_membership_graph_is_rejected(session: Session):
    selected = _candidate("selected")
    unassigned = _candidate("unassigned")

    with pytest.raises(DecisionPersistenceIntegrityError, match="exactly cover"):
        DecisionEvaluationRepository(session).save(
            _artifacts(
                decision_id="decision-incomplete-membership",
                selected=selected,
                candidates=(selected, unassigned),
            )
        )


@pytest.mark.parametrize(
    ("field_name", "payload", "message"),
    [
        (
            "policy_results",
            {"unknown": PolicyResult(allowed=True)},
            "policy result references unknown",
        ),
        (
            "predictions",
            {"unknown": _prediction("unknown")},
            "prediction references unknown",
        ),
        (
            "scores",
            {"unknown": _score("unknown", utility_score=0.0)},
            "score references unknown",
        ),
    ],
)
def test_unknown_candidate_child_artifact_is_rejected(
    session: Session,
    field_name: str,
    payload: object,
    message: str,
):
    selected = _candidate("known")
    base = _artifacts(decision_id=f"decision-unknown-{field_name}", selected=selected)
    artifacts = base.model_copy(update={field_name: payload})

    with pytest.raises(DecisionPersistenceIntegrityError, match=message):
        DecisionEvaluationRepository(session).save(artifacts)


def test_unknown_ranking_candidate_is_rejected(session: Session):
    selected = _candidate("known-ranking")
    unknown = _candidate("unknown-ranking")
    unknown_score = _score(unknown.id, utility_score=1.0)
    ranking = (RankedCandidate(rank=1, candidate=unknown, score=unknown_score),)

    with pytest.raises(DecisionPersistenceIntegrityError, match="unknown candidate"):
        DecisionEvaluationRepository(session).save(
            _artifacts(
                decision_id="decision-unknown-ranking",
                selected=selected,
                scores={unknown.id: unknown_score},
                ranking=ranking,
            )
        )


def test_unknown_confidence_candidate_is_rejected(session: Session):
    selected = _candidate("known-confidence")
    confidence = _confidence("unknown-confidence")

    with pytest.raises(DecisionPersistenceIntegrityError, match="unknown candidate"):
        DecisionEvaluationRepository(session).save(
            _artifacts(
                decision_id="decision-unknown-confidence",
                selected=selected,
                confidence=confidence,
                result_confidence=confidence.prediction_reliability,
            )
        )


def test_duplicate_rank_is_rejected(session: Session):
    selected = _candidate("rank-a")
    alternative = _candidate("rank-b")
    score_a = _score(selected.id, utility_score=1.0)
    score_b = _score(alternative.id, utility_score=2.0)
    ranking = (
        RankedCandidate(rank=1, candidate=selected, score=score_a),
        RankedCandidate(rank=1, candidate=alternative, score=score_b),
    )

    with pytest.raises(DecisionPersistenceIntegrityError, match="duplicate rank"):
        DecisionEvaluationRepository(session).save(
            _artifacts(
                decision_id="decision-duplicate-rank",
                selected=selected,
                alternatives=(alternative,),
                scores={selected.id: score_a, alternative.id: score_b},
                ranking=ranking,
            )
        )


def test_duplicate_ranked_candidate_is_rejected(session: Session):
    selected = _candidate("rank-duplicate")
    score = _score(selected.id, utility_score=1.0)
    ranking = (
        RankedCandidate(rank=1, candidate=selected, score=score),
        RankedCandidate(rank=2, candidate=selected, score=score),
    )

    with pytest.raises(DecisionPersistenceIntegrityError, match="duplicate candidate"):
        DecisionEvaluationRepository(session).save(
            _artifacts(
                decision_id="decision-duplicate-ranked-candidate",
                selected=selected,
                scores={selected.id: score},
                ranking=ranking,
            )
        )


def test_confidence_candidate_may_reference_known_non_selected_candidate(
    session: Session,
):
    selected = _candidate("selected-confidence-owner")
    alternative = _candidate("other-confidence-owner")
    confidence = _confidence(alternative.id)

    row = DecisionEvaluationRepository(session).save(
        _artifacts(
            decision_id="decision-confidence-owner",
            selected=selected,
            alternatives=(alternative,),
            confidence=confidence,
            result_confidence=0.25,
        )
    )

    candidate_rows = _candidate_rows(row)
    assert row.selected_candidate_id == candidate_rows[selected.id].id
    assert row.confidence_artifact is not None
    assert row.confidence_artifact.candidate_id == candidate_rows[alternative.id].id


def test_ranking_embedded_score_must_match_supplied_score(session: Session):
    selected = _candidate("ranking-score")
    supplied = _score(selected.id, utility_score=1.0)
    embedded = _score(selected.id, utility_score=2.0)

    with pytest.raises(DecisionPersistenceIntegrityError, match="differs"):
        DecisionEvaluationRepository(session).save(
            _artifacts(
                decision_id="decision-ranking-score-mismatch",
                selected=selected,
                scores={selected.id: supplied},
                ranking=(RankedCandidate(rank=1, candidate=selected, score=embedded),),
            )
        )


def test_retrieval_returns_stored_graph_without_recomputation(session: Session):
    selected = _candidate("retrieve-selected")
    alternative = _candidate("retrieve-alt")
    rejected = _candidate("retrieve-rejected")
    score_selected = _score(selected.id, utility_score=-5.0)
    score_alt = _score(alternative.id, utility_score=100.0)
    prediction = _prediction(selected.id)
    confidence = _confidence(selected.id)
    policy = PolicyResult(
        allowed=False,
        violations=["required_evidence_missing"],
    )
    ranking = (
        RankedCandidate(rank=1, candidate=selected, score=score_selected),
        RankedCandidate(rank=2, candidate=alternative, score=score_alt),
    )
    base = _artifacts(
        decision_id="decision-retrieve",
        selected=selected,
        alternatives=(alternative,),
        rejected=(rejected,),
        policy_results={rejected.id: policy},
        predictions={selected.id: prediction},
        scores={selected.id: score_selected, alternative.id: score_alt},
        ranking=ranking,
        confidence=confidence,
        result_confidence=confidence.prediction_reliability,
    )
    artifacts = base.model_copy(
        update={"explanation": _explanation(base.result, confidence)}
    )
    repository = DecisionEvaluationRepository(session)
    repository.save(artifacts)

    row = repository.get_by_decision_id("decision-retrieve")

    assert row is not None
    rows = _candidate_rows(row)
    assert rows[selected.id].score.utility_score == -5.0
    assert rows[alternative.id].score.utility_score == 100.0
    assert rows[rejected.id].policy_result is not None
    assert json.loads(rows[rejected.id].policy_result.violations_json) == [
        "required_evidence_missing"
    ]
    assert row.confidence_artifact is not None
    assert row.explanation is not None


def test_duplicate_decision_id_rejected_without_replacing_existing_graph(
    session: Session,
):
    repository = DecisionEvaluationRepository(session)
    first = repository.save(
        _artifacts(
            decision_id="decision-duplicate-id",
            selected=_candidate("duplicate-id-first"),
        )
    )

    with pytest.raises(DecisionPersistenceIntegrityError, match="already exists"):
        repository.save(
            _artifacts(
                decision_id="decision-duplicate-id",
                selected=_candidate("duplicate-id-second"),
            )
        )

    stored = repository.get_by_decision_id("decision-duplicate-id")
    assert stored is not None
    assert stored.id == first.id
    assert session.query(DecisionEvaluationDB).count() == 1
    assert [candidate.candidate_id for candidate in stored.candidates] == [
        "duplicate-id-first"
    ]


def test_save_requires_clean_session_without_touching_caller_pending_state(
    session: Session,
):
    unrelated = AlgorithmDB(
        algorithm_id="pending-algorithm",
        canonical_name="pending",
        display_name="Pending",
        status="active",
        source="test",
    )
    session.add(unrelated)
    assert inspect(unrelated).pending
    assert unrelated in session.new

    with pytest.raises(DecisionPersistenceIntegrityError, match="clean/dedicated Session"):
        DecisionEvaluationRepository(session).save(
            _artifacts(decision_id="decision-clean-session")
        )

    assert inspect(unrelated).pending
    assert unrelated in session.new
    assert not any(
        isinstance(obj, DecisionEvaluationDB)
        for obj in session.new
    )


def test_save_requires_clean_session_for_dirty_and_deleted_state(session: Session):
    dirty = AlgorithmDB(
        algorithm_id="dirty-algorithm",
        canonical_name="dirty",
        display_name="Dirty",
        status="active",
        source="test",
    )
    deleted = AlgorithmDB(
        algorithm_id="deleted-algorithm",
        canonical_name="deleted",
        display_name="Deleted",
        status="active",
        source="test",
    )
    session.add_all([dirty, deleted])
    session.commit()

    dirty.display_name = "Dirty changed"
    session.delete(deleted)
    assert dirty in session.dirty
    assert deleted in session.deleted

    with pytest.raises(DecisionPersistenceIntegrityError, match="clean/dedicated Session"):
        DecisionEvaluationRepository(session).save(
            _artifacts(decision_id="decision-dirty-session")
        )

    assert dirty in session.dirty
    assert deleted in session.deleted


def test_successful_save_does_not_reload_after_commit(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    repository = DecisionEvaluationRepository(session)

    def fail_reload(_decision_id: str) -> DecisionEvaluationDB | None:
        raise AssertionError("save must not call get_by_decision_id after commit")

    monkeypatch.setattr(repository, "get_by_decision_id", fail_reload)

    row = repository.save(
        _artifacts(
            decision_id="decision-no-post-commit-reload",
            selected=_candidate("no-post-commit-reload"),
        )
    )

    assert row.decision_id == "decision-no-post-commit-reload"
    assert session.query(DecisionEvaluationDB).count() == 1


def test_commit_failure_rolls_back_complete_graph(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    original_commit = session.commit

    def fail_commit() -> None:
        raise RuntimeError("forced commit failure")

    monkeypatch.setattr(session, "commit", fail_commit)

    with pytest.raises(RuntimeError, match="forced commit failure"):
        DecisionEvaluationRepository(session).save(
            _artifacts(
                decision_id="decision-commit-failure",
                selected=_candidate("commit-failure"),
            )
        )

    monkeypatch.setattr(session, "commit", original_commit)
    assert session.query(DecisionEvaluationDB).count() == 0
    assert session.query(DecisionCandidateDB).count() == 0


def test_atomic_rollback_removes_root_candidates_and_children_after_child_failure(
    session: Session,
):
    selected = _candidate("rollback-selected")
    score = _score(selected.id, utility_score=7.0)
    artifacts = _artifacts(
        decision_id="decision-rollback",
        selected=selected,
        scores={selected.id: score},
    )

    def fail_score_insert(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("forced child insert failure")

    event.listen(DecisionScoreDB, "before_insert", fail_score_insert)
    try:
        with pytest.raises(RuntimeError, match="forced child insert failure"):
            DecisionEvaluationRepository(session).save(artifacts)
    finally:
        event.remove(DecisionScoreDB, "before_insert", fail_score_insert)

    assert session.query(DecisionEvaluationDB).count() == 0
    assert session.query(DecisionCandidateDB).count() == 0
    assert session.query(DecisionPolicyResultDB).count() == 0
    assert session.query(DecisionPredictionDB).count() == 0
    assert session.query(DecisionScoreDB).count() == 0
    assert session.query(DecisionRankingDB).count() == 0
    assert session.query(DecisionConfidenceDB).count() == 0
    assert session.query(DecisionExplanationDB).count() == 0


def test_validation_failure_also_leaves_no_partial_graph(session: Session):
    selected = _candidate("validation-rollback")
    duplicate = selected.model_copy()

    with pytest.raises(DecisionPersistenceIntegrityError):
        DecisionEvaluationRepository(session).save(
            _artifacts(
                decision_id="decision-validation-rollback",
                selected=selected,
                candidates=(selected, duplicate),
            )
        )

    assert session.query(DecisionEvaluationDB).count() == 0
    assert session.query(DecisionCandidateDB).count() == 0


def test_cross_evaluation_selected_row_substitution_is_rejected(session: Session):
    first = DecisionEvaluationRepository(session).save(
        _artifacts(decision_id="decision-owner-a", selected=_candidate("shared"))
    )
    external_row = _candidate_rows(first)["shared"]

    class SubstitutingRepository(DecisionEvaluationRepository):
        def _persist_candidates(self, **kwargs):
            rows = super()._persist_candidates(**kwargs)
            rows["shared"] = external_row
            return rows

    with pytest.raises(DecisionPersistenceIntegrityError, match="another decision evaluation"):
        SubstitutingRepository(session).save(
            _artifacts(decision_id="decision-owner-b", selected=_candidate("shared"))
        )

    assert session.query(DecisionEvaluationDB).count() == 1


def test_cross_evaluation_ranking_row_substitution_is_rejected(session: Session):
    first_candidate = _candidate("external-ranked")
    first = DecisionEvaluationRepository(session).save(
        _artifacts(decision_id="decision-rank-owner-a", selected=first_candidate)
    )
    external_row = _candidate_rows(first)[first_candidate.id]

    selected = _candidate("local-ranked")
    selected_score = _score(selected.id, utility_score=1.0)
    ranking = (RankedCandidate(rank=1, candidate=selected, score=selected_score),)

    class SubstitutingRepository(DecisionEvaluationRepository):
        def _persist_rankings(self, evaluation, ranking, candidate_rows):
            row = DecisionRankingDB(
                decision_evaluation_id=evaluation.id,
                candidate_id=external_row.id,
                rank_position=1,
            )
            self.session.add(row)
            return [row]

    with pytest.raises(DecisionPersistenceIntegrityError, match="ranking candidate"):
        SubstitutingRepository(session).save(
            _artifacts(
                decision_id="decision-rank-owner-b",
                selected=selected,
                scores={selected.id: selected_score},
                ranking=ranking,
            )
        )

    assert session.query(DecisionEvaluationDB).count() == 1


def test_cross_evaluation_confidence_row_substitution_is_rejected(session: Session):
    first_candidate = _candidate("external-confidence")
    first = DecisionEvaluationRepository(session).save(
        _artifacts(decision_id="decision-confidence-owner-a", selected=first_candidate)
    )
    external_row = _candidate_rows(first)[first_candidate.id]

    selected = _candidate("local-confidence")
    confidence = _confidence(selected.id)

    class SubstitutingRepository(DecisionEvaluationRepository):
        def _persist_confidence(self, evaluation, confidence, candidate_rows):
            row = DecisionConfidenceDB(
                decision_evaluation_id=evaluation.id,
                candidate_id=external_row.id,
                evidence_inputs_json="[]",
                context_freshness="fresh",
                miner_freshness="fresh",
                hardware_freshness="fresh",
                prediction_reliability=0.67,
                overall_confidence=None,
                limitations_json="[]",
            )
            self.session.add(row)
            return row

    with pytest.raises(DecisionPersistenceIntegrityError, match="confidence candidate"):
        SubstitutingRepository(session).save(
            _artifacts(
                decision_id="decision-confidence-owner-b",
                selected=selected,
                confidence=confidence,
                result_confidence=0.67,
            )
        )

    assert session.query(DecisionEvaluationDB).count() == 1



def test_load_artifacts_round_trip_preserves_complete_graph_without_recomputation(
    session: Session,
):
    selected = _candidate(
        "roundtrip-selected",
        expected_gain=2.5,
        confidence=0.51,
        risk_score=0.33,
        transition_cost=0.44,
    )
    alternative = _candidate(
        "roundtrip-alternative",
        action_type=ActionType.EVALUATE_NETWORK,
        expected_gain=3.0,
        confidence=0.61,
        risk_score=0.21,
        transition_cost=0.55,
    )
    rejected = _candidate(
        "roundtrip-rejected",
        action_type=ActionType.NO_ACTION,
        expected_gain=0.0,
        confidence=0.95,
        risk_score=0.0,
        transition_cost=0.0,
    )
    policy = PolicyResult(
        allowed=False,
        violations=["required_evidence_missing", "confidence_below_minimum"],
    )
    prediction = PredictionResult(
        candidate_id=selected.id,
        expected_reward_change=None,
        expected_hashrate_change=12.75,
        expected_power_change=None,
        confidence=0.41,
        uncertainty=0.59,
        horizon=PredictionHorizon.LONG_TERM,
        rationale="persisted prediction rationale",
    )
    selected_score = DecisionScore(
        candidate_id=selected.id,
        benefit=9.0,
        confidence=0.12,
        risk=0.87,
        action_cost=4.5,
        uncertainty=0.63,
        utility_score=-123.456,
    )
    rejected_score = DecisionScore(
        candidate_id=rejected.id,
        benefit=0.0,
        confidence=0.99,
        risk=0.01,
        action_cost=0.0,
        uncertainty=0.02,
        utility_score=777.0,
    )
    ranking = (
        RankedCandidate(rank=4, candidate=selected, score=selected_score),
        RankedCandidate(rank=1, candidate=rejected, score=rejected_score),
    )
    confidence = _confidence(
        alternative.id,
        prediction_reliability=0.70,
        overall_confidence=0.90,
    )
    timestamp = datetime(
        2026,
        9,
        19,
        1,
        2,
        3,
        456789,
        tzinfo=timezone(timedelta(hours=3)),
    )
    base = _artifacts(
        decision_id="decision-roundtrip-complete",
        selected=selected,
        alternatives=(alternative,),
        rejected=(rejected,),
        candidates=(rejected, alternative, selected),
        policy_results={rejected.id: policy},
        predictions={selected.id: prediction},
        scores={
            selected.id: selected_score,
            rejected.id: rejected_score,
        },
        ranking=ranking,
        confidence=confidence,
        result_confidence=0.25,
        timestamp=timestamp,
    )
    explanation = _explanation(base.result, confidence)
    artifacts = base.model_copy(update={"explanation": explanation})

    repository = DecisionEvaluationRepository(session)
    repository.save(artifacts)
    loaded = repository.load_artifacts(artifacts.result.decision_id)

    assert loaded is not None
    assert loaded.timestamp == timestamp
    assert loaded.session_id is None
    assert loaded.result == artifacts.result
    assert loaded.candidates == (selected, alternative, rejected)
    assert loaded.policy_results == {rejected.id: policy}
    assert loaded.predictions == {selected.id: prediction}
    assert loaded.scores == {
        selected.id: selected_score,
        rejected.id: rejected_score,
    }
    assert [(item.candidate.id, item.rank) for item in loaded.ranking] == [
        (rejected.id, 1),
        (selected.id, 4),
    ]
    assert loaded.ranking[0].score == rejected_score
    assert loaded.ranking[1].score == selected_score
    assert loaded.confidence == confidence
    assert loaded.explanation == explanation
    assert loaded.result.confidence == 0.25
    assert loaded.confidence.prediction_reliability == 0.70
    assert loaded.confidence.overall_confidence == 0.90


@pytest.mark.parametrize(
    ("role", "selected", "alternatives", "rejected"),
    [
        (
            "selected",
            _candidate("load-no-action-selected", action_type=ActionType.NO_ACTION),
            (),
            (),
        ),
        (
            "alternative",
            _candidate("load-alt-selected"),
            (_candidate("load-no-action-alt", action_type=ActionType.NO_ACTION),),
            (),
        ),
        (
            "rejected",
            _candidate("load-reject-selected"),
            (),
            (_candidate("load-no-action-rejected", action_type=ActionType.NO_ACTION),),
        ),
    ],
)
def test_load_artifacts_preserves_no_action_in_all_result_roles(
    session: Session,
    role: str,
    selected: CandidateAction,
    alternatives: tuple[CandidateAction, ...],
    rejected: tuple[CandidateAction, ...],
):
    artifacts = _artifacts(
        decision_id=f"decision-load-no-action-{role}",
        selected=selected,
        alternatives=alternatives,
        rejected=rejected,
    )
    repository = DecisionEvaluationRepository(session)
    repository.save(artifacts)

    loaded = repository.load_artifacts(artifacts.result.decision_id)

    assert loaded is not None
    no_action_candidates = [
        candidate
        for candidate in loaded.candidates
        if candidate.action_type is ActionType.NO_ACTION
    ]
    assert len(no_action_candidates) == 1
    no_action = no_action_candidates[0]
    if role == "selected":
        assert loaded.result.selected_action == no_action
    elif role == "alternative":
        assert loaded.result.alternatives == [no_action]
    else:
        assert loaded.result.rejected_alternatives == [no_action]


def test_load_artifacts_supports_no_selection_with_rejected_candidate(
    session: Session,
):
    rejected = _candidate("load-no-selection-rejected")
    artifacts = _artifacts(
        decision_id="decision-load-no-selection-rejected",
        selected=None,
        rejected=(rejected,),
        candidates=(rejected,),
        auto_select=False,
    )
    repository = DecisionEvaluationRepository(session)
    repository.save(artifacts)

    loaded = repository.load_artifacts(artifacts.result.decision_id)

    assert loaded is not None
    assert loaded.result.selected_action is None
    assert loaded.result.alternatives == []
    assert loaded.result.rejected_alternatives == [rejected]
    assert loaded.candidates == (rejected,)


def test_load_artifacts_supports_no_selection_with_zero_candidates(session: Session):
    artifacts = _artifacts(
        decision_id="decision-load-no-selection-empty",
        selected=None,
        candidates=(),
        auto_select=False,
    )
    repository = DecisionEvaluationRepository(session)
    repository.save(artifacts)

    loaded = repository.load_artifacts(artifacts.result.decision_id)

    assert loaded is not None
    assert loaded.result.selected_action is None
    assert loaded.candidates == ()
    assert loaded.ranking == ()
    assert loaded.confidence is None


def test_load_artifacts_supports_no_selection_with_known_confidence_candidate(
    session: Session,
):
    candidate = _candidate("load-no-selection-confidence")
    confidence = _confidence(
        candidate.id,
        prediction_reliability=0.70,
        overall_confidence=None,
    )
    artifacts = _artifacts(
        decision_id="decision-load-no-selection-confidence",
        selected=None,
        rejected=(candidate,),
        candidates=(candidate,),
        confidence=confidence,
        result_confidence=0.25,
        auto_select=False,
    )
    repository = DecisionEvaluationRepository(session)
    repository.save(artifacts)

    loaded = repository.load_artifacts(artifacts.result.decision_id)

    assert loaded is not None
    assert loaded.result.selected_action is None
    assert loaded.result.confidence == 0.25
    assert loaded.confidence == confidence
    assert loaded.confidence.prediction_reliability == 0.70
    assert loaded.confidence.overall_confidence is None


@pytest.mark.parametrize(
    "timestamp",
    [
        datetime(2026, 9, 19, 1, 2, 3, 456789),
        datetime(2026, 9, 19, 1, 2, 3, 456789, tzinfo=UTC),
        datetime(
            2026,
            9,
            19,
            1,
            2,
            3,
            456789,
            tzinfo=timezone(timedelta(hours=3)),
        ),
        datetime(
            2026,
            9,
            19,
            1,
            2,
            3,
            456789,
            tzinfo=timezone(-timedelta(hours=5, minutes=30)),
        ),
        datetime(2026, 9, 19, 1, 2, 3, 0, tzinfo=UTC),
    ],
)
def test_load_artifacts_reconstructs_timestamp_from_authoritative_iso(
    session: Session,
    timestamp: datetime,
):
    artifacts = _artifacts(
        decision_id=f"decision-load-timestamp-{timestamp.isoformat()}",
        timestamp=timestamp,
    )
    repository = DecisionEvaluationRepository(session)
    row = repository.save(artifacts)

    row.timestamp = datetime(1999, 1, 1, 0, 0, 0)
    session.commit()
    loaded = repository.load_artifacts(artifacts.result.decision_id)

    assert loaded is not None
    assert loaded.timestamp == timestamp
    assert loaded.timestamp.tzinfo == timestamp.tzinfo
    assert loaded.timestamp.microsecond == timestamp.microsecond


@pytest.mark.parametrize("session_id", [None, "session-roundtrip"])
def test_load_artifacts_preserves_optional_session_id(
    session: Session,
    session_id: str | None,
):
    if session_id is not None:
        session.add(
            SessionDB(
                session_id=session_id,
                start_time=datetime(2026, 9, 19, 0, 0, 0),
            )
        )
        session.commit()

    artifacts = _artifacts(
        decision_id=f"decision-load-session-{session_id}",
        session_id=session_id,
    )
    repository = DecisionEvaluationRepository(session)
    repository.save(artifacts)

    loaded = repository.load_artifacts(artifacts.result.decision_id)

    assert loaded is not None
    assert loaded.session_id == session_id


def test_load_artifacts_returns_none_for_missing_decision(session: Session):
    loaded = DecisionEvaluationRepository(session).load_artifacts("missing-decision")

    assert loaded is None


def test_load_artifacts_is_read_only(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    artifacts = _artifacts(
        decision_id="decision-load-read-only",
        selected=_candidate("load-read-only"),
    )
    repository = DecisionEvaluationRepository(session)
    repository.save(artifacts)

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("load_artifacts must not perform repository writes")

    monkeypatch.setattr(session, "add", fail_write)
    monkeypatch.setattr(session, "delete", fail_write)
    monkeypatch.setattr(session, "flush", fail_write)
    monkeypatch.setattr(session, "commit", fail_write)
    monkeypatch.setattr(session, "rollback", fail_write)

    loaded = repository.load_artifacts(artifacts.result.decision_id)

    assert loaded is not None
    assert loaded.result.decision_id == artifacts.result.decision_id


def test_load_artifacts_rejects_corrupted_authoritative_timestamp(session: Session):
    artifacts = _artifacts(decision_id="decision-load-bad-timestamp")
    repository = DecisionEvaluationRepository(session)
    row = repository.save(artifacts)
    row.timestamp_iso = "not-an-iso-timestamp"
    session.commit()

    with pytest.raises(
        DecisionPersistenceIntegrityError,
        match="persisted decision evaluation is invalid",
    ):
        repository.load_artifacts(artifacts.result.decision_id)


def test_load_artifacts_rejects_malformed_structured_explanation(session: Session):
    base = _artifacts(
        decision_id="decision-load-bad-explanation",
        selected=_candidate("load-bad-explanation"),
    )
    artifacts = base.model_copy(update={"explanation": _explanation(base.result)})
    repository = DecisionEvaluationRepository(session)
    row = repository.save(artifacts)
    assert row.explanation is not None
    row.explanation.explanation_json = "{malformed"
    session.commit()

    with pytest.raises(
        DecisionPersistenceIntegrityError,
        match="persisted decision evaluation is invalid",
    ):
        repository.load_artifacts(artifacts.result.decision_id)


def test_load_artifacts_rejects_malformed_confidence_json(session: Session):
    candidate = _candidate("load-bad-confidence-json")
    confidence = _confidence(candidate.id)
    artifacts = _artifacts(
        decision_id="decision-load-bad-confidence-json",
        selected=candidate,
        confidence=confidence,
        result_confidence=0.25,
    )
    repository = DecisionEvaluationRepository(session)
    row = repository.save(artifacts)
    assert row.confidence_artifact is not None
    row.confidence_artifact.evidence_inputs_json = "{malformed"
    session.commit()

    with pytest.raises(
        DecisionPersistenceIntegrityError,
        match="persisted decision evaluation is invalid",
    ):
        repository.load_artifacts(artifacts.result.decision_id)


def test_load_artifacts_rejects_ranking_without_persisted_score(session: Session):
    candidate = _candidate("load-ranking-missing-score")
    score = _score(candidate.id, utility_score=314.0)
    artifacts = _artifacts(
        decision_id="decision-load-ranking-missing-score",
        selected=candidate,
        scores={candidate.id: score},
        ranking=(RankedCandidate(rank=3, candidate=candidate, score=score),),
    )
    repository = DecisionEvaluationRepository(session)
    row = repository.save(artifacts)
    candidate_row = _candidate_rows(row)[candidate.id]
    assert candidate_row.score is not None
    session.delete(candidate_row.score)
    session.commit()
    session.expire_all()

    with pytest.raises(
        DecisionPersistenceIntegrityError,
        match="missing persisted DecisionScore",
    ):
        repository.load_artifacts(artifacts.result.decision_id)


def test_load_artifacts_rejects_cross_evaluation_selected_candidate(session: Session):
    first_candidate = _candidate("load-external-selected")
    first = DecisionEvaluationRepository(session).save(
        _artifacts(
            decision_id="decision-load-owner-a",
            selected=first_candidate,
        )
    )
    external_row = _candidate_rows(first)[first_candidate.id]

    second_candidate = _candidate("load-local-selected")
    second = DecisionEvaluationRepository(session).save(
        _artifacts(
            decision_id="decision-load-owner-b",
            selected=second_candidate,
        )
    )
    second.selected_candidate_id = external_row.id
    session.commit()
    session.expire_all()

    with pytest.raises(
        DecisionPersistenceIntegrityError,
        match="outside this decision evaluation",
    ):
        DecisionEvaluationRepository(session).load_artifacts(
            "decision-load-owner-b"
        )


def test_load_artifacts_rejects_cross_evaluation_ranking_candidate(session: Session):
    external_candidate = _candidate("load-external-ranked")
    first = DecisionEvaluationRepository(session).save(
        _artifacts(
            decision_id="decision-load-rank-owner-a",
            selected=external_candidate,
        )
    )
    external_row = _candidate_rows(first)[external_candidate.id]

    local_candidate = _candidate("load-local-ranked")
    local_score = _score(local_candidate.id, utility_score=8.0)
    second = DecisionEvaluationRepository(session).save(
        _artifacts(
            decision_id="decision-load-rank-owner-b",
            selected=local_candidate,
            scores={local_candidate.id: local_score},
            ranking=(
                RankedCandidate(
                    rank=8,
                    candidate=local_candidate,
                    score=local_score,
                ),
            ),
        )
    )
    second.rankings[0].candidate_id = external_row.id
    session.commit()
    session.expire_all()

    with pytest.raises(
        DecisionPersistenceIntegrityError,
        match="outside this decision evaluation",
    ):
        DecisionEvaluationRepository(session).load_artifacts(
            "decision-load-rank-owner-b"
        )


def test_load_artifacts_rejects_invalid_candidate_enum(session: Session):
    artifacts = _artifacts(
        decision_id="decision-load-invalid-enum",
        selected=_candidate("load-invalid-enum"),
    )
    repository = DecisionEvaluationRepository(session)
    row = repository.save(artifacts)
    row.candidates[0].action_type = "not_a_real_action"
    session.commit()
    session.expire_all()

    with pytest.raises(
        DecisionPersistenceIntegrityError,
        match="persisted decision evaluation is invalid",
    ):
        repository.load_artifacts(artifacts.result.decision_id)


def test_repository_source_has_no_decision_recomputation_or_execution_surfaces():
    source = (
        Path(__file__).parents[2]
        / "src"
        / "mining_guardian"
        / "storage"
        / "decision_repository.py"
    ).read_text()

    forbidden = (
        "DecisionScorer(",
        "DecisionRanker(",
        "DecisionConfidenceEngine(",
        "DecisionExplainer(",
        "OutcomePredictor(",
        "CandidateGenerator(",
        "subprocess",
        "pynvml",
        "httpx",
        "requests",
    )
    for token in forbidden:
        assert token not in source
