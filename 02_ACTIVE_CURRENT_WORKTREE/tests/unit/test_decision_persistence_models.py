import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DateTime, Float, Text, inspect

from mining_guardian.agent.cognition.enums import Reliability
from mining_guardian.agent.decision.confidence import (
    ConfidenceLimitation,
    DecisionConfidenceResult,
    EvidenceConfidenceInput,
)
from mining_guardian.agent.decision.models import CandidateAction, DecisionResult
from mining_guardian.agent.decision.predictors import (
    PredictionHorizon,
    PredictionResult,
)
from mining_guardian.agent.temporal import FreshnessLevel
from mining_guardian.storage.schema import (
    Base,
    DecisionCandidateDB,
    DecisionConfidenceDB,
    DecisionEvaluationDB,
    DecisionExplanationDB,
    DecisionPolicyResultDB,
    DecisionPredictionDB,
    DecisionRankingDB,
    DecisionScoreDB,
)


def _unique_constraint_names(model: type) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
        and constraint.name is not None
    }


def _check_constraint_names(model: type) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
        and constraint.name is not None
    }


def test_decision_models_register_tables():
    tables = Base.metadata.tables
    assert {
        "decision_evaluations",
        "decision_candidates",
        "decision_policy_results",
        "decision_predictions",
        "decision_scores",
        "decision_rankings",
        "decision_confidence",
        "decision_explanations",
    } <= set(tables)


def test_decision_evaluation_timestamp_authority_is_explicit():
    timestamp = inspect(DecisionEvaluationDB).columns.timestamp
    timestamp_iso = inspect(DecisionEvaluationDB).columns.timestamp_iso

    assert timestamp.nullable is False
    assert isinstance(timestamp.type, DateTime)
    assert timestamp.comment is not None
    assert "Convenience/query snapshot" in timestamp.comment

    assert timestamp_iso.nullable is False
    assert isinstance(timestamp_iso.type, Text)
    assert timestamp_iso.comment is not None
    assert "Authoritative ISO-8601" in timestamp_iso.comment


def test_selected_candidate_is_nullable_and_targets_persisted_candidate_row():
    selected = inspect(DecisionEvaluationDB).columns.selected_candidate_id

    assert selected.nullable is True
    assert selected.type.python_type is int
    assert {
        foreign_key.target_fullname for foreign_key in selected.foreign_keys
    } == {"decision_candidates.id"}


def test_confidence_ownership_is_explicit_and_nullable():
    evaluation_confidence = inspect(DecisionEvaluationDB).columns.confidence
    authoritative_confidence = inspect(DecisionConfidenceDB).columns.overall_confidence

    assert evaluation_confidence.nullable is True
    assert authoritative_confidence.nullable is True
    assert evaluation_confidence.comment is not None
    assert "Non-authoritative snapshot" in evaluation_confidence.comment
    assert authoritative_confidence.comment is not None
    assert "Authoritative persisted Phase 9" in authoritative_confidence.comment


def test_explanation_ownership_is_explicit():
    evaluation_explanation = inspect(DecisionEvaluationDB).columns.explanation_json
    authoritative_explanation = inspect(DecisionExplanationDB).columns.explanation_json

    assert evaluation_explanation.nullable is True
    assert evaluation_explanation.comment is not None
    assert "Non-authoritative snapshot" in evaluation_explanation.comment
    assert authoritative_explanation.nullable is False
    assert authoritative_explanation.comment is not None
    assert "Authoritative persisted structured Phase 11" in authoritative_explanation.comment


def test_decision_evaluation_relationships_are_registered():
    relationships = inspect(DecisionEvaluationDB).relationships

    assert relationships["candidates"].mapper.class_ is DecisionCandidateDB
    assert relationships["selected_candidate"].mapper.class_ is DecisionCandidateDB
    assert relationships["rankings"].mapper.class_ is DecisionRankingDB
    assert relationships["confidence_artifact"].mapper.class_ is DecisionConfidenceDB
    assert relationships["confidence_artifact"].uselist is False
    assert relationships["explanation"].mapper.class_ is DecisionExplanationDB
    assert relationships["explanation"].uselist is False


def test_candidate_child_relationships_are_registered_as_singletons():
    relationships = inspect(DecisionCandidateDB).relationships

    assert relationships["policy_result"].mapper.class_ is DecisionPolicyResultDB
    assert relationships["policy_result"].uselist is False
    assert relationships["prediction"].mapper.class_ is DecisionPredictionDB
    assert relationships["prediction"].uselist is False
    assert relationships["score"].mapper.class_ is DecisionScoreDB
    assert relationships["score"].uselist is False
    assert relationships["ranking"].mapper.class_ is DecisionRankingDB
    assert relationships["ranking"].uselist is False


def test_candidate_child_foreign_keys_use_persistence_row_identity():
    expected = {
        DecisionPolicyResultDB: "decision_candidates.id",
        DecisionPredictionDB: "decision_candidates.id",
        DecisionScoreDB: "decision_candidates.id",
        DecisionRankingDB: "decision_candidates.id",
    }

    for model, target in expected.items():
        column = inspect(model).columns.candidate_id
        assert column.type.python_type is int
        assert {foreign_key.target_fullname for foreign_key in column.foreign_keys} == {
            target
        }


def test_candidate_result_membership_preserves_selected_and_collection_order():
    selected = DecisionCandidateDB(
        decision_evaluation_id=1,
        candidate_id="selected",
        action_type="evaluate_efficiency",
        execution_category="recommendation_only",
        description="selected",
        expected_gain=1.0,
        confidence=0.8,
        risk_score=0.1,
        transition_cost=0.1,
        reversible=True,
        result_role="selected",
        result_position=None,
    )
    alternatives = [
        DecisionCandidateDB(
            decision_evaluation_id=1,
            candidate_id=f"alternative-{position}",
            action_type="evaluate_efficiency",
            execution_category="recommendation_only",
            description="alternative",
            expected_gain=1.0,
            confidence=0.8,
            risk_score=0.1,
            transition_cost=0.1,
            reversible=True,
            result_role="alternative",
            result_position=position,
        )
        for position in (0, 1)
    ]
    rejected = [
        DecisionCandidateDB(
            decision_evaluation_id=1,
            candidate_id=f"rejected-{position}",
            action_type="evaluate_network",
            execution_category="observation_only",
            description="rejected",
            expected_gain=0.0,
            confidence=0.0,
            risk_score=0.0,
            transition_cost=0.0,
            reversible=True,
            result_role="rejected",
            result_position=position,
        )
        for position in (0, 1)
    ]

    assert selected.result_role == "selected"
    assert selected.result_position is None
    assert [candidate.result_position for candidate in alternatives] == [0, 1]
    assert [candidate.result_position for candidate in rejected] == [0, 1]
    assert {candidate.result_role for candidate in alternatives} == {"alternative"}
    assert {candidate.result_role for candidate in rejected} == {"rejected"}


def test_result_membership_does_not_depend_on_policy_or_ranking_inference():
    alternative = DecisionCandidateDB(
        decision_evaluation_id=1,
        candidate_id="same-domain-shape-a",
        action_type="evaluate_network",
        execution_category="observation_only",
        description="candidate",
        expected_gain=0.0,
        confidence=0.0,
        risk_score=0.0,
        transition_cost=0.0,
        reversible=True,
        result_role="alternative",
        result_position=0,
    )
    rejected = DecisionCandidateDB(
        decision_evaluation_id=1,
        candidate_id="same-domain-shape-b",
        action_type="evaluate_network",
        execution_category="observation_only",
        description="candidate",
        expected_gain=0.0,
        confidence=0.0,
        risk_score=0.0,
        transition_cost=0.0,
        reversible=True,
        result_role="rejected",
        result_position=0,
    )

    assert alternative.policy_result is None
    assert alternative.ranking is None
    assert rejected.policy_result is None
    assert rejected.ranking is None
    assert alternative.result_role != rejected.result_role


def test_no_action_can_use_any_result_role_without_special_persistence_fields():
    candidates = [
        DecisionCandidateDB(
            decision_evaluation_id=1,
            candidate_id=f"no-action-{role}",
            action_type="no_action",
            execution_category="observation_only",
            description="no action",
            expected_gain=0.0,
            confidence=0.0,
            risk_score=0.0,
            transition_cost=0.0,
            reversible=True,
            result_role=role,
            result_position=None if role == "selected" else 0,
        )
        for role in ("selected", "alternative", "rejected")
    ]

    assert [candidate.action_type for candidate in candidates] == ["no_action"] * 3
    assert [candidate.result_role for candidate in candidates] == [
        "selected",
        "alternative",
        "rejected",
    ]


def test_result_membership_constraints_are_portable_and_explicit():
    unique_names = _unique_constraint_names(DecisionCandidateDB)
    check_names = _check_constraint_names(DecisionCandidateDB)

    assert "uq_decision_candidate_result_position" in unique_names
    assert "ck_decision_candidate_result_role" in check_names
    assert "ck_decision_candidate_result_position" in check_names


def test_result_membership_metadata_does_not_change_candidate_action_contract():
    assert "result_role" not in CandidateAction.model_fields
    assert "result_position" not in CandidateAction.model_fields


def test_candidate_uniqueness_remains_scoped_to_decision_evaluation():
    names = _unique_constraint_names(DecisionCandidateDB)

    assert "uq_decision_candidate" in names
    candidate_column = inspect(DecisionCandidateDB).columns.candidate_id
    assert candidate_column.unique is not True


def test_policy_result_cardinality_is_zero_or_one_per_candidate():
    assert "uq_decision_policy_candidate" in _unique_constraint_names(
        DecisionPolicyResultDB
    )


def test_prediction_cardinality_is_zero_or_one_per_candidate():
    assert "uq_decision_prediction_candidate" in _unique_constraint_names(
        DecisionPredictionDB
    )


def test_score_cardinality_is_zero_or_one_per_candidate():
    assert "uq_decision_score_candidate" in _unique_constraint_names(DecisionScoreDB)


def test_ranking_constraints_preserve_rank_and_candidate_uniqueness():
    names = _unique_constraint_names(DecisionRankingDB)

    assert "uq_decision_ranking_decision_rank" in names
    assert "uq_decision_ranking_candidate" in names
    assert "uq_decision_ranking_candidate_row" in names


def test_confidence_cardinality_is_zero_or_one_per_evaluation():
    assert "uq_decision_confidence_evaluation" in _unique_constraint_names(
        DecisionConfidenceDB
    )


def test_explanation_cardinality_is_zero_or_one_per_evaluation():
    assert "uq_decision_explanation_evaluation" in _unique_constraint_names(
        DecisionExplanationDB
    )


def test_no_persistence_service_layer_exists():
    storage_dir = Path(__file__).parents[2] / "src" / "mining_guardian" / "storage"

    assert not (storage_dir / "decision_service.py").exists()


def test_prediction_rationale_storage_matches_current_contract():
    rationale_field = PredictionResult.model_fields["rationale"]
    rationale_column = inspect(DecisionPredictionDB).columns.rationale

    assert rationale_field.default is None
    assert rationale_column.nullable is True
    assert isinstance(rationale_column.type, Text)


def test_confidence_schema_matches_current_contract_without_legacy_collapsing():
    columns = inspect(DecisionConfidenceDB).columns

    assert "evidence_quality" not in columns
    assert "freshness" not in columns
    assert {
        "candidate_id",
        "evidence_inputs_json",
        "context_freshness",
        "miner_freshness",
        "hardware_freshness",
        "prediction_reliability",
        "overall_confidence",
        "limitations_json",
    } <= set(columns.keys())

    assert columns.candidate_id.type.python_type is int
    assert {
        foreign_key.target_fullname for foreign_key in columns.candidate_id.foreign_keys
    } == {"decision_candidates.id"}
    assert isinstance(columns.evidence_inputs_json.type, Text)
    assert columns.context_freshness.type.python_type is str
    assert columns.miner_freshness.type.python_type is str
    assert columns.hardware_freshness.type.python_type is str
    assert isinstance(columns.prediction_reliability.type, Float)
    assert columns.prediction_reliability.type.python_type is float
    assert columns.overall_confidence.nullable is True
    assert isinstance(columns.limitations_json.type, Text)


def test_confidence_structured_inputs_are_losslessly_representable():
    confidence = DecisionConfidenceResult(
        candidate_id="candidate-selected",
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
        prediction_reliability=0.625,
        overall_confidence=None,
        limitations=[
            ConfidenceLimitation.NUMERIC_EVIDENCE_QUALITY_UNAVAILABLE,
            ConfidenceLimitation.NUMERIC_FRESHNESS_FACTOR_UNAVAILABLE,
        ],
    )

    evidence_inputs_json = json.dumps(
        [item.model_dump(mode="json") for item in confidence.evidence_inputs]
    )
    limitations_json = json.dumps([item.value for item in confidence.limitations])
    row = DecisionConfidenceDB(
        decision_evaluation_id=1,
        candidate_id=2,
        evidence_inputs_json=evidence_inputs_json,
        context_freshness=confidence.context_freshness.value,
        miner_freshness=confidence.miner_freshness.value,
        hardware_freshness=confidence.hardware_freshness.value,
        prediction_reliability=confidence.prediction_reliability,
        overall_confidence=confidence.overall_confidence,
        limitations_json=limitations_json,
    )

    assert json.loads(row.evidence_inputs_json) == [
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
    assert row.context_freshness == "recent"
    assert row.miner_freshness == "fresh"
    assert row.hardware_freshness == "stale"
    assert row.prediction_reliability == 0.625
    assert row.overall_confidence is None
    assert json.loads(row.limitations_json) == [
        "numeric_evidence_quality_unavailable",
        "numeric_freshness_factor_unavailable",
    ]


def test_decision_result_explanation_has_distinct_required_storage():
    result_field = DecisionResult.model_fields["explanation"]
    result_explanation = inspect(DecisionEvaluationDB).columns.result_explanation
    structured_snapshot = inspect(DecisionEvaluationDB).columns.explanation_json
    structured_authoritative = inspect(DecisionExplanationDB).columns.explanation_json

    assert result_field.is_required()
    assert result_explanation.nullable is False
    assert isinstance(result_explanation.type, Text)
    assert result_explanation.comment is not None
    assert "DecisionResult.explanation" in result_explanation.comment

    assert structured_snapshot.nullable is True
    assert structured_snapshot.comment is not None
    assert "Non-authoritative snapshot" in structured_snapshot.comment
    assert structured_authoritative.nullable is False
    assert structured_authoritative.comment is not None
    assert "Authoritative persisted structured Phase 11" in structured_authoritative.comment


def test_representative_prediction_and_decision_result_values_fit_models_exactly():
    prediction = PredictionResult(
        candidate_id="candidate-selected",
        expected_reward_change=1.125,
        expected_hashrate_change=None,
        expected_power_change=-2.5,
        confidence=0.75,
        uncertainty=0.2,
        horizon=PredictionHorizon.SHORT_TERM,
        rationale="Existing deterministic predictor rationale.",
    )
    prediction_row = DecisionPredictionDB(
        candidate_id=1,
        expected_reward_change=prediction.expected_reward_change,
        expected_hashrate_change=prediction.expected_hashrate_change,
        expected_power_change=prediction.expected_power_change,
        confidence=prediction.confidence,
        uncertainty=prediction.uncertainty,
        horizon=prediction.horizon.value,
        rationale=prediction.rationale,
    )

    result = DecisionResult(
        decision_id="decision-fidelity",
        state="approved",
        confidence=0.75,
        explanation="Deterministic Phase 10 DecisionResult explanation.",
    )
    evaluation_timestamp = datetime(2026, 9, 19, tzinfo=UTC)
    evaluation_row = DecisionEvaluationDB(
        decision_id=result.decision_id,
        timestamp=evaluation_timestamp,
        timestamp_iso=evaluation_timestamp.isoformat(timespec="microseconds"),
        state=result.state,
        selected_candidate_id=None,
        confidence=result.confidence,
        result_explanation=result.explanation,
        explanation_json=None,
    )

    assert prediction_row.rationale == prediction.rationale
    assert prediction_row.expected_reward_change == 1.125
    assert prediction_row.expected_hashrate_change is None
    assert prediction_row.expected_power_change == -2.5
    assert evaluation_row.timestamp == evaluation_timestamp
    assert evaluation_row.timestamp_iso == "2026-09-19T00:00:00.000000+00:00"
    assert evaluation_row.result_explanation == result.explanation
    assert evaluation_row.explanation_json is None

