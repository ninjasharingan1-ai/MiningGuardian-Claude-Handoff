import inspect

import pytest
from pydantic import ValidationError

import mining_guardian.agent.decision.scoring as scoring_module
from mining_guardian.agent.decision import (
    ActionType,
    CandidateAction,
    CandidateGenerator,
    DecisionContext,
    DecisionPolicy,
    DecisionResult,
    DecisionScore,
    DecisionScorer,
    ExecutionCategory,
    OutcomePredictor,
    PolicyResult,
    PredictionHorizon,
    PredictionResult,
)
from mining_guardian.agent.decision.lifecycle import DecisionState, can_transition


def _candidate(
    *,
    action_type: ActionType = ActionType.INVESTIGATE_PERFORMANCE,
    expected_gain: float = 0.05,
    confidence: float = 0.8,
    risk_score: float = 0.1,
    transition_cost: float = 0.02,
) -> CandidateAction:
    return CandidateAction(
        id=f"candidate-{action_type.value}",
        action_type=action_type,
        description=f"Candidate {action_type.value}",
        execution_category=ExecutionCategory.OBSERVATION_ONLY,
        expected_gain=expected_gain,
        confidence=confidence,
        risk_score=risk_score,
        transition_cost=transition_cost,
        reversible=True,
    )


def _prediction(
    candidate: CandidateAction,
    *,
    expected_reward_change: float | None = 0.05,
    confidence: float = 0.8,
    uncertainty: float = 0.1,
) -> PredictionResult:
    return PredictionResult(
        candidate_id=candidate.id,
        expected_reward_change=expected_reward_change,
        expected_hashrate_change=None,
        expected_power_change=None,
        confidence=confidence,
        uncertainty=uncertainty,
        horizon=PredictionHorizon.SHORT_TERM,
        rationale="Scoring contract test.",
    )


def test_decision_score_valid_construction():
    score = DecisionScore(
        candidate_id="candidate-1",
        benefit=0.05,
        confidence=0.8,
        risk=0.1,
        action_cost=0.02,
        uncertainty=0.1,
        utility_score=-0.18,
    )

    assert score.candidate_id == "candidate-1"


def test_decision_score_serialization_round_trip():
    score = DecisionScore(
        candidate_id="candidate-2",
        benefit=0.2,
        confidence=0.9,
        risk=0.1,
        action_cost=0.01,
        uncertainty=0.02,
        utility_score=0.05,
    )

    restored = DecisionScore.model_validate_json(score.model_dump_json())

    assert restored == score


def test_candidate_identity_is_preserved():
    candidate = _candidate()
    score = DecisionScorer().score(candidate, _prediction(candidate))

    assert score.candidate_id == candidate.id


def test_prediction_candidate_identity_must_match():
    candidate = _candidate()
    prediction = _prediction(candidate).model_copy(
        update={"candidate_id": "different-candidate"}
    )

    with pytest.raises(ValueError, match="candidate_id"):
        DecisionScorer().score(candidate, prediction)


def test_exact_adr_0006_formula():
    candidate = _candidate(
        expected_gain=99.0,
        risk_score=1.0,
        transition_cost=2.0,
    )
    prediction = _prediction(
        candidate,
        expected_reward_change=10.0,
        confidence=0.8,
        uncertainty=0.5,
    )

    score = DecisionScorer().score(candidate, prediction)

    assert score.benefit == 10.0
    assert score.confidence == 0.8
    assert score.risk == 1.0
    assert score.action_cost == 2.0
    assert score.uncertainty == 0.5
    assert score.utility_score == 4.5


def test_formula_guard_rejects_unauthorized_alternative_math_by_expected_value():
    candidate = _candidate(risk_score=0.37, transition_cost=0.19)
    prediction = _prediction(
        candidate,
        expected_reward_change=0.83,
        confidence=0.61,
        uncertainty=0.23,
    )

    score = DecisionScorer().score(candidate, prediction)
    exact_adr_score = (0.83 * 0.61) - (0.37 + 0.19 + 0.23)

    assert score.utility_score == exact_adr_score
    assert score.utility_score != 0.83 + 0.61 - 0.37


def test_prediction_benefit_takes_precedence_over_candidate_expected_gain():
    candidate = _candidate(expected_gain=0.9)
    prediction = _prediction(candidate, expected_reward_change=0.2)

    score = DecisionScorer().score(candidate, prediction)

    assert score.benefit == 0.2


def test_candidate_expected_gain_is_fallback_when_prediction_benefit_unknown():
    candidate = _candidate(expected_gain=0.3)
    prediction = _prediction(candidate, expected_reward_change=None)

    score = DecisionScorer().score(candidate, prediction)

    assert score.benefit == 0.3


def test_prediction_confidence_is_used_without_combining_candidate_confidence():
    candidate = _candidate(confidence=0.2, risk_score=0.0, transition_cost=0.0)
    prediction = _prediction(
        candidate,
        expected_reward_change=1.0,
        confidence=0.7,
        uncertainty=0.0,
    )

    score = DecisionScorer().score(candidate, prediction)

    assert score.confidence == 0.7
    assert score.utility_score == 0.7


def test_increasing_benefit_increases_score():
    candidate = _candidate(risk_score=0.1, transition_cost=0.1)
    low = DecisionScorer().score(
        candidate,
        _prediction(candidate, expected_reward_change=0.2, uncertainty=0.1),
    )
    high = DecisionScorer().score(
        candidate,
        _prediction(candidate, expected_reward_change=0.4, uncertainty=0.1),
    )

    assert high.utility_score > low.utility_score


def test_increasing_confidence_increases_score_for_positive_benefit():
    candidate = _candidate(risk_score=0.1, transition_cost=0.1)
    low = DecisionScorer().score(
        candidate,
        _prediction(
            candidate,
            expected_reward_change=1.0,
            confidence=0.4,
            uncertainty=0.1,
        ),
    )
    high = DecisionScorer().score(
        candidate,
        _prediction(
            candidate,
            expected_reward_change=1.0,
            confidence=0.8,
            uncertainty=0.1,
        ),
    )

    assert high.utility_score > low.utility_score


def test_increasing_risk_lowers_score():
    low_risk_candidate = _candidate(risk_score=0.1)
    high_risk_candidate = _candidate(risk_score=0.4)
    low_risk_prediction = _prediction(low_risk_candidate)
    high_risk_prediction = _prediction(high_risk_candidate)

    low_risk = DecisionScorer().score(low_risk_candidate, low_risk_prediction)
    high_risk = DecisionScorer().score(high_risk_candidate, high_risk_prediction)

    assert high_risk.utility_score < low_risk.utility_score


def test_increasing_action_cost_lowers_score():
    low_cost_candidate = _candidate(transition_cost=0.1)
    high_cost_candidate = _candidate(transition_cost=0.4)

    low_cost = DecisionScorer().score(
        low_cost_candidate,
        _prediction(low_cost_candidate),
    )
    high_cost = DecisionScorer().score(
        high_cost_candidate,
        _prediction(high_cost_candidate),
    )

    assert high_cost.utility_score < low_cost.utility_score


def test_increasing_uncertainty_lowers_score():
    candidate = _candidate()
    low = DecisionScorer().score(
        candidate,
        _prediction(candidate, uncertainty=0.1),
    )
    high = DecisionScorer().score(
        candidate,
        _prediction(candidate, uncertainty=0.4),
    )

    assert high.utility_score < low.utility_score


def test_zero_benefit_uses_exact_formula():
    candidate = _candidate(risk_score=0.1, transition_cost=0.2)
    prediction = _prediction(
        candidate,
        expected_reward_change=0.0,
        confidence=0.9,
        uncertainty=0.3,
    )

    score = DecisionScorer().score(candidate, prediction)

    assert score.utility_score == pytest.approx(-0.6)


def test_zero_confidence_uses_exact_formula():
    candidate = _candidate(risk_score=0.1, transition_cost=0.2)
    prediction = _prediction(
        candidate,
        expected_reward_change=10.0,
        confidence=0.0,
        uncertainty=0.3,
    )

    score = DecisionScorer().score(candidate, prediction)

    assert score.utility_score == pytest.approx(-0.6)


def test_zero_penalties_yield_benefit_times_confidence():
    candidate = _candidate(risk_score=0.0, transition_cost=0.0)
    prediction = _prediction(
        candidate,
        expected_reward_change=0.8,
        confidence=0.5,
        uncertainty=0.0,
    )

    score = DecisionScorer().score(candidate, prediction)

    assert score.utility_score == 0.4


def test_negative_utility_is_not_clamped():
    candidate = _candidate(risk_score=0.8, transition_cost=0.5)
    prediction = _prediction(
        candidate,
        expected_reward_change=0.1,
        confidence=0.5,
        uncertainty=0.4,
    )

    score = DecisionScorer().score(candidate, prediction)

    assert score.utility_score == pytest.approx(-1.65)
    assert score.utility_score < 0.0


def test_no_action_uses_same_scoring_equation_without_bonus_or_penalty():
    candidate = _candidate(
        action_type=ActionType.NO_ACTION,
        expected_gain=0.0,
        risk_score=0.2,
        transition_cost=0.1,
    )
    prediction = _prediction(
        candidate,
        expected_reward_change=0.0,
        confidence=0.9,
        uncertainty=0.3,
    )

    score = DecisionScorer().score(candidate, prediction)

    assert score.utility_score == pytest.approx(-0.6)


def test_same_inputs_produce_identical_score():
    candidate = _candidate()
    prediction = _prediction(candidate)
    scorer = DecisionScorer()

    assert scorer.score(candidate, prediction) == scorer.score(candidate, prediction)


def test_scoring_does_not_mutate_candidate_or_prediction():
    candidate = _candidate()
    prediction = _prediction(candidate)
    candidate_before = candidate.model_dump()
    prediction_before = prediction.model_dump()

    DecisionScorer().score(candidate, prediction)

    assert candidate.model_dump() == candidate_before
    assert prediction.model_dump() == prediction_before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confidence", -0.01),
        ("confidence", 1.01),
        ("risk", -0.01),
        ("risk", 1.01),
        ("uncertainty", -0.01),
        ("uncertainty", 1.01),
        ("action_cost", -0.01),
    ],
)
def test_decision_score_validation_rejects_invalid_values(field: str, value: float):
    values = {
        "candidate_id": "candidate-validation",
        "benefit": 0.1,
        "confidence": 0.5,
        "risk": 0.2,
        "action_cost": 0.1,
        "uncertainty": 0.2,
        "utility_score": -0.25,
    }
    values[field] = value

    with pytest.raises(ValidationError):
        DecisionScore(**values)


def test_scoring_module_contains_only_direct_formula_without_weight_configuration():
    source = inspect.getsource(scoring_module)

    assert "weight" not in source.lower()
    assert "coefficient" not in source.lower()
    assert "multiplier" not in source.lower()


def test_scoring_module_has_no_ml_llm_or_external_io_dependencies():
    source = inspect.getsource(scoring_module).lower()

    forbidden = (
        "openai",
        "anthropic",
        "httpx",
        "requests",
        "subprocess",
        "pynvml",
        "srminer",
        "sqlalchemy",
        "socket",
    )
    assert not any(term in source for term in forbidden)


def test_prior_phase_contracts_remain_importable():
    assert ActionType.NO_ACTION.value == "no_action"
    assert ExecutionCategory.FUTURE_CONTROL.value == "future_control"
    assert CandidateAction is not None
    assert DecisionResult is not None
    assert DecisionState.DETECTED.value == "detected"
    assert can_transition(DecisionState.DETECTED, DecisionState.ANALYZING)
    assert DecisionContext is not None
    assert CandidateGenerator is not None
    assert DecisionPolicy is not None
    assert PolicyResult is not None
    assert OutcomePredictor is not None
    assert PredictionResult is not None


def test_scoring_is_independent_of_decision_context_and_external_state():
    signature = inspect.signature(DecisionScorer.score)

    assert list(signature.parameters) == ["self", "candidate", "prediction"]


def test_future_control_gains_no_execution_behavior():
    candidate = CandidateAction(
        id="candidate-future-control",
        action_type=ActionType.EVALUATE_EFFICIENCY,
        description="Metadata-only future control candidate.",
        execution_category=ExecutionCategory.FUTURE_CONTROL,
        expected_gain=0.1,
        confidence=0.8,
        risk_score=0.1,
        transition_cost=0.1,
    )

    assert not hasattr(candidate, "execute")
    assert not hasattr(candidate, "apply")
    assert not hasattr(candidate, "control")
