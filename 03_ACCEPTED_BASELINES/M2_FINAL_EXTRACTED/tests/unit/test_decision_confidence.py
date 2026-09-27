import inspect

import pytest
from pydantic import ValidationError

import mining_guardian.agent.decision.confidence as confidence_module
from mining_guardian.agent.cognition.claims import Claim
from mining_guardian.agent.cognition.enums import (
    ClaimStatus,
    ClaimType,
    Confidence,
    EvidenceType,
    HypothesisStatus,
    Reliability,
)
from mining_guardian.agent.cognition.evidence import EvidenceItem
from mining_guardian.agent.cognition.hypotheses import Hypothesis
from mining_guardian.agent.decision import (
    ActionType,
    CandidateAction,
    CandidateGenerator,
    ConfidenceLimitation,
    DecisionConfidenceEngine,
    DecisionConfidenceResult,
    DecisionContext,
    DecisionPolicy,
    DecisionRanker,
    DecisionResult,
    DecisionScore,
    DecisionScorer,
    EvidenceConfidenceInput,
    ExecutionCategory,
    OutcomePredictor,
    PolicyResult,
    PredictionHorizon,
    PredictionResult,
    RankedCandidate,
)
from mining_guardian.agent.decision.lifecycle import DecisionState, can_transition
from mining_guardian.agent.temporal import FreshnessLevel, FreshnessPolicy


def _evidence(
    *,
    evidence_id: str = "evidence-1",
    reliability: Reliability = Reliability.HIGH,
    freshness: FreshnessLevel = FreshnessLevel.FRESH,
) -> EvidenceItem:
    return EvidenceItem(
        id=evidence_id,
        evidence_type=EvidenceType.MEASURED,
        source="confidence-test",
        value={"signal": "validated"},
        freshness=freshness,
        reliability=reliability,
        metadata={"decision_domain": "performance"},
    )


def _claim(evidence_id: str = "evidence-1") -> Claim:
    return Claim(
        id="claim-1",
        statement="The measured condition is supported.",
        claim_type=ClaimType.OBSERVATION,
        supporting_evidence_ids=[evidence_id],
        confidence=Confidence.HIGH,
        status=ClaimStatus.SUPPORTED,
    )


def _hypothesis(evidence_id: str = "evidence-1") -> Hypothesis:
    return Hypothesis(
        id="hypothesis-1",
        statement="The supported condition warrants investigation.",
        supporting_evidence_ids=[evidence_id],
        confidence=Confidence.MEDIUM,
        status=HypothesisStatus.SUPPORTED,
    )


def _context(
    *,
    evidence: list[EvidenceItem] | None = None,
    freshness: FreshnessLevel = FreshnessLevel.FRESH,
    miner_freshness: FreshnessLevel = FreshnessLevel.FRESH,
    hardware_freshness: FreshnessLevel = FreshnessLevel.FRESH,
) -> DecisionContext:
    items = [_evidence()] if evidence is None else evidence
    evidence_id = items[0].id if items else "absent-evidence"
    return DecisionContext(
        evidence=items,
        claims=[_claim(evidence_id)] if items else [],
        hypotheses=[_hypothesis(evidence_id)] if items else [],
        freshness=freshness,
        miner_freshness=miner_freshness,
        hardware_freshness=hardware_freshness,
        decision_constraints=["read_only"],
    )


def _prediction(
    candidate_id: str = "candidate-performance",
    *,
    confidence: float = 0.8,
) -> PredictionResult:
    return PredictionResult(
        candidate_id=candidate_id,
        expected_reward_change=None,
        expected_hashrate_change=None,
        expected_power_change=None,
        confidence=confidence,
        uncertainty=0.2,
        horizon=PredictionHorizon.SHORT_TERM,
        rationale="Contract-only prediction reliability.",
    )


def _candidate(
    candidate_id: str,
    action_type: ActionType,
    *,
    reversible: bool = True,
) -> CandidateAction:
    return CandidateAction(
        id=candidate_id,
        action_type=action_type,
        description=f"Candidate {candidate_id}",
        execution_category=ExecutionCategory.OBSERVATION_ONLY,
        expected_gain=0.0,
        confidence=0.0,
        risk_score=0.0,
        transition_cost=0.0,
        reversible=reversible,
    )


def _score(candidate_id: str, utility_score: float) -> DecisionScore:
    return DecisionScore(
        candidate_id=candidate_id,
        benefit=0.0,
        confidence=0.8,
        risk=0.0,
        action_cost=0.0,
        uncertainty=0.2,
        utility_score=utility_score,
    )


def test_decision_confidence_result_valid_construction():
    result = DecisionConfidenceResult(
        candidate_id="candidate-1",
        evidence_inputs=[
            EvidenceConfidenceInput(
                evidence_id="evidence-1",
                reliability=Reliability.HIGH,
                freshness=FreshnessLevel.FRESH,
            )
        ],
        context_freshness=FreshnessLevel.FRESH,
        miner_freshness=FreshnessLevel.FRESH,
        hardware_freshness=FreshnessLevel.RECENT,
        prediction_reliability=0.8,
        overall_confidence=None,
        limitations=[
            ConfidenceLimitation.NUMERIC_EVIDENCE_QUALITY_UNAVAILABLE,
            ConfidenceLimitation.NUMERIC_FRESHNESS_FACTOR_UNAVAILABLE,
        ],
    )

    assert result.candidate_id == "candidate-1"
    assert result.prediction_reliability == 0.8
    assert result.overall_confidence is None


def test_decision_confidence_result_serialization_round_trip():
    result = DecisionConfidenceEngine().evaluate(_context(), _prediction())

    restored = DecisionConfidenceResult.model_validate_json(result.model_dump_json())

    assert restored == result


def test_evidence_reliability_uses_existing_reliability_enum():
    evidence = _evidence(reliability=Reliability.MEDIUM)

    result = DecisionConfidenceEngine().evaluate(
        _context(evidence=[evidence]),
        _prediction(),
    )

    assert result.evidence_inputs[0].reliability is Reliability.MEDIUM


@pytest.mark.parametrize(
    "freshness",
    [
        FreshnessLevel.FRESH,
        FreshnessLevel.RECENT,
        FreshnessLevel.STALE,
        FreshnessLevel.UNKNOWN,
    ],
)
def test_existing_freshness_semantics_are_preserved(freshness: FreshnessLevel):
    result = DecisionConfidenceEngine().evaluate(
        _context(freshness=freshness),
        _prediction(),
    )

    assert result.context_freshness is freshness


def test_existing_evidence_freshness_is_preserved():
    evidence = _evidence(freshness=FreshnessLevel.RECENT)

    result = DecisionConfidenceEngine().evaluate(
        _context(evidence=[evidence]),
        _prediction(),
    )

    assert result.evidence_inputs[0].freshness is FreshnessLevel.RECENT


def test_no_new_freshness_thresholds_are_introduced():
    source = inspect.getsource(confidence_module)

    assert "FreshnessPolicy(" not in source
    assert "classify_age" not in source
    assert "classify_timestamp" not in source
    assert "fresh_max_age_seconds" not in source
    assert "recent_max_age_seconds" not in source


def test_existing_freshness_policy_contract_remains_compatible():
    policy = FreshnessPolicy()

    assert policy.classify_age(0.0) is FreshnessLevel.FRESH


def test_prediction_reliability_comes_from_prediction_result():
    prediction = _prediction(confidence=0.63)

    result = DecisionConfidenceEngine().evaluate(_context(), prediction)

    assert result.prediction_reliability == 0.63


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_decision_confidence_prediction_reliability_is_bounded(value: float):
    with pytest.raises(ValidationError):
        DecisionConfidenceResult(
            candidate_id="candidate",
            context_freshness=FreshnessLevel.FRESH,
            miner_freshness=FreshnessLevel.FRESH,
            hardware_freshness=FreshnessLevel.FRESH,
            prediction_reliability=value,
        )


def test_same_inputs_produce_identical_result():
    context = _context()
    prediction = _prediction()
    engine = DecisionConfidenceEngine()

    first = engine.evaluate(context, prediction)
    second = engine.evaluate(context, prediction)

    assert first == second


def test_confidence_evaluation_does_not_mutate_context_or_cognitive_objects():
    context = _context()
    evidence = context.evidence[0]
    claim = context.claims[0]
    hypothesis = context.hypotheses[0]
    prediction = _prediction()

    context_before = context.model_dump()
    evidence_before = evidence.model_dump()
    claim_before = claim.model_dump()
    hypothesis_before = hypothesis.model_dump()
    prediction_before = prediction.model_dump()

    DecisionConfidenceEngine().evaluate(context, prediction)

    assert context.model_dump() == context_before
    assert evidence.model_dump() == evidence_before
    assert claim.model_dump() == claim_before
    assert hypothesis.model_dump() == hypothesis_before
    assert prediction.model_dump() == prediction_before


def test_no_action_receives_no_hidden_confidence_bonus_or_penalty():
    context = _context()
    engine = DecisionConfidenceEngine()

    no_action = engine.evaluate(context, _prediction("no-action", confidence=0.7))
    actionable = engine.evaluate(
        context,
        _prediction("investigate-performance", confidence=0.7),
    )

    assert no_action.model_copy(update={"candidate_id": "same"}) == actionable.model_copy(
        update={"candidate_id": "same"}
    )


def test_missing_evidence_is_represented_safely():
    result = DecisionConfidenceEngine().evaluate(
        _context(evidence=[]),
        _prediction(),
    )

    assert result.evidence_inputs == []
    assert result.overall_confidence is None
    assert ConfidenceLimitation.NO_EVIDENCE in result.limitations


def test_unknown_context_freshness_is_represented_safely():
    result = DecisionConfidenceEngine().evaluate(
        _context(freshness=FreshnessLevel.UNKNOWN),
        _prediction(),
    )

    assert result.context_freshness is FreshnessLevel.UNKNOWN
    assert result.overall_confidence is None
    assert ConfidenceLimitation.UNKNOWN_CONTEXT_FRESHNESS in result.limitations


def test_stale_context_freshness_is_preserved_as_limitation():
    result = DecisionConfidenceEngine().evaluate(
        _context(freshness=FreshnessLevel.STALE),
        _prediction(),
    )

    assert result.context_freshness is FreshnessLevel.STALE
    assert ConfidenceLimitation.STALE_CONTEXT_FRESHNESS in result.limitations


def test_unknown_evidence_reliability_is_not_mapped_to_numeric_value():
    result = DecisionConfidenceEngine().evaluate(
        _context(evidence=[_evidence(reliability=Reliability.UNKNOWN)]),
        _prediction(),
    )

    assert result.evidence_inputs[0].reliability is Reliability.UNKNOWN
    assert result.overall_confidence is None
    assert ConfidenceLimitation.UNKNOWN_EVIDENCE_RELIABILITY in result.limitations


def test_unknown_evidence_freshness_is_not_mapped_to_numeric_value():
    result = DecisionConfidenceEngine().evaluate(
        _context(evidence=[_evidence(freshness=FreshnessLevel.UNKNOWN)]),
        _prediction(),
    )

    assert result.evidence_inputs[0].freshness is FreshnessLevel.UNKNOWN
    assert result.overall_confidence is None
    assert ConfidenceLimitation.UNKNOWN_EVIDENCE_FRESHNESS in result.limitations


def test_stale_evidence_is_preserved_as_limitation():
    result = DecisionConfidenceEngine().evaluate(
        _context(evidence=[_evidence(freshness=FreshnessLevel.STALE)]),
        _prediction(),
    )

    assert result.evidence_inputs[0].freshness is FreshnessLevel.STALE
    assert ConfidenceLimitation.STALE_EVIDENCE in result.limitations


def test_prediction_reliability_is_not_optional_in_current_phase_six_contract():
    assert PredictionResult.model_fields["confidence"].is_required()


def test_no_artificial_optimistic_confidence_for_complete_high_quality_inputs():
    result = DecisionConfidenceEngine().evaluate(
        _context(
            evidence=[
                _evidence(
                    reliability=Reliability.HIGH,
                    freshness=FreshnessLevel.FRESH,
                )
            ],
            freshness=FreshnessLevel.FRESH,
        ),
        _prediction(confidence=1.0),
    )

    assert result.overall_confidence is None


def test_adr_aggregate_confidence_remains_unavailable_without_numeric_mappings():
    result = DecisionConfidenceEngine().evaluate(_context(), _prediction())

    assert result.overall_confidence is None
    assert (
        ConfidenceLimitation.NUMERIC_EVIDENCE_QUALITY_UNAVAILABLE
        in result.limitations
    )
    assert (
        ConfidenceLimitation.NUMERIC_FRESHNESS_FACTOR_UNAVAILABLE
        in result.limitations
    )


def test_no_weighted_or_invented_confidence_formula_exists():
    source = inspect.getsource(confidence_module)

    forbidden = [
        "weighted_",
        "average(",
        "mean(",
        "geometric",
        "freshness_factor =",
        "reliability_factor =",
    ]
    assert all(token not in source for token in forbidden)


def test_freshness_categories_are_not_silently_mapped_to_numeric_constants():
    fresh = DecisionConfidenceEngine().evaluate(
        _context(freshness=FreshnessLevel.FRESH),
        _prediction(),
    )
    stale = DecisionConfidenceEngine().evaluate(
        _context(freshness=FreshnessLevel.STALE),
        _prediction(),
    )

    assert fresh.context_freshness is FreshnessLevel.FRESH
    assert stale.context_freshness is FreshnessLevel.STALE
    assert fresh.overall_confidence is None
    assert stale.overall_confidence is None


def test_confidence_evaluation_does_not_modify_decision_score():
    score = DecisionScore(
        candidate_id="candidate-performance",
        benefit=0.4,
        confidence=0.8,
        risk=0.1,
        action_cost=0.05,
        uncertainty=0.2,
        utility_score=-0.03,
    )
    before = score.model_dump()

    DecisionConfidenceEngine().evaluate(_context(), _prediction(score.candidate_id))

    assert score.model_dump() == before
    assert score.utility_score == -0.03


def test_confidence_evaluation_does_not_reorder_existing_ranking():
    candidates = [
        _candidate("first", ActionType.INVESTIGATE_PERFORMANCE),
        _candidate("second", ActionType.EVALUATE_NETWORK),
    ]
    scores = [_score("first", 0.7), _score("second", 0.2)]
    ranker = DecisionRanker()
    before = ranker.rank(candidates, scores)

    DecisionConfidenceEngine().evaluate(
        _context(),
        _prediction("second", confidence=1.0),
    )

    after = ranker.rank(candidates, scores)

    assert [item.candidate.id for item in before] == ["first", "second"]
    assert [item.candidate.id for item in after] == ["first", "second"]


def test_confidence_module_has_no_scoring_or_ranking_calls():
    source = inspect.getsource(confidence_module)

    assert "DecisionScorer" not in source
    assert "DecisionRanker" not in source
    assert "utility_score" not in source


def test_phase_one_contracts_remain_compatible():
    action = _candidate("phase-1", ActionType.NO_ACTION)
    result = DecisionResult(
        decision_id="decision-1",
        state="proposed",
        selected_action=action,
        confidence=0.0,
        explanation="Compatibility check.",
    )

    assert result.selected_action is action


def test_phase_two_lifecycle_remains_compatible():
    assert can_transition(DecisionState.DETECTED, DecisionState.ANALYZING)


def test_phase_three_decision_context_remains_compatible():
    context = _context()

    assert context.evidence[0].id == "evidence-1"


def test_phase_four_candidate_generator_remains_compatible():
    candidates = CandidateGenerator().generate(_context())

    assert candidates[0].action_type is ActionType.NO_ACTION


def test_phase_five_policy_contracts_remain_compatible():
    assert DecisionPolicy is not None
    assert PolicyResult is not None


def test_phase_six_prediction_contracts_remain_compatible():
    assert OutcomePredictor is not None
    assert _prediction().horizon is PredictionHorizon.SHORT_TERM


def test_phase_seven_scoring_contracts_remain_compatible():
    assert DecisionScorer is not None
    assert DecisionScore is not None


def test_phase_eight_ranking_contracts_remain_compatible():
    assert DecisionRanker is not None
    assert RankedCandidate is not None


def test_phase_nine_exports_are_public():
    assert DecisionConfidenceEngine is not None
    assert DecisionConfidenceResult is not None
    assert EvidenceConfidenceInput is not None
    assert ConfidenceLimitation is not None
