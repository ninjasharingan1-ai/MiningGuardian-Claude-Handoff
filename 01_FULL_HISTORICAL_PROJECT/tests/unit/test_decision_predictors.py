import inspect
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

import mining_guardian.agent.decision.predictors as predictor_module
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
    DecisionContext,
    DecisionPolicy,
    DecisionResult,
    ExecutionCategory,
    OutcomePredictor,
    PolicyResult,
    PredictionHorizon,
    PredictionResult,
    evaluate_policy,
)
from mining_guardian.agent.decision.lifecycle import DecisionState, can_transition
from mining_guardian.agent.temporal import FreshnessLevel


def _context() -> DecisionContext:
    evidence = EvidenceItem(
        id="evidence-performance",
        evidence_type=EvidenceType.MEASURED,
        source="prediction-boundary-test",
        value={"condition": "performance"},
        observed_at=datetime(2026, 9, 17, tzinfo=UTC),
        freshness=FreshnessLevel.FRESH,
        reliability=Reliability.HIGH,
        metadata={"decision_domain": "performance"},
    )
    claim = Claim(
        id="claim-performance",
        statement="Performance condition is supported.",
        claim_type=ClaimType.OBSERVATION,
        supporting_evidence_ids=[evidence.id],
        confidence=Confidence.HIGH,
        status=ClaimStatus.SUPPORTED,
    )
    hypothesis = Hypothesis(
        id="hypothesis-performance",
        statement="Performance condition warrants investigation.",
        supporting_evidence_ids=[evidence.id],
        confidence=Confidence.MEDIUM,
        status=HypothesisStatus.SUPPORTED,
    )
    return DecisionContext(
        evidence=[evidence],
        claims=[claim],
        hypotheses=[hypothesis],
        freshness=FreshnessLevel.FRESH,
        miner_freshness=FreshnessLevel.FRESH,
        hardware_freshness=FreshnessLevel.FRESH,
        decision_constraints=["read_only"],
    )


def _candidate(
    *,
    expected_gain: float = 0.05,
    confidence: float = 0.8,
) -> CandidateAction:
    return CandidateAction(
        id="candidate-investigate-performance",
        action_type=ActionType.INVESTIGATE_PERFORMANCE,
        description="Investigate supported performance condition.",
        execution_category=ExecutionCategory.OBSERVATION_ONLY,
        expected_gain=expected_gain,
        confidence=confidence,
        risk_score=0.1,
        transition_cost=0.0,
        reversible=True,
    )


class _ContractPredictor:
    """Test-only implementation proving the Protocol boundary is usable."""

    def predict(
        self,
        context: DecisionContext,
        candidate: CandidateAction,
    ) -> PredictionResult:
        assert isinstance(context, DecisionContext)
        return PredictionResult(
            candidate_id=candidate.id,
            expected_reward_change=candidate.expected_gain,
            confidence=candidate.confidence,
            uncertainty=0.0,
            horizon=PredictionHorizon.IMMEDIATE,
            rationale="Test-only pass-through contract.",
        )


def test_prediction_result_valid_construction():
    result = PredictionResult(
        candidate_id="candidate-1",
        expected_reward_change=0.05,
        expected_hashrate_change=None,
        expected_power_change=None,
        confidence=0.8,
        uncertainty=0.2,
        horizon=PredictionHorizon.SHORT_TERM,
        rationale="Structured contract only.",
    )

    assert result.candidate_id == "candidate-1"
    assert result.expected_reward_change == 0.05
    assert result.expected_hashrate_change is None
    assert result.expected_power_change is None


def test_prediction_result_serialization_round_trip():
    result = PredictionResult(
        candidate_id="candidate-2",
        expected_reward_change=None,
        expected_hashrate_change=None,
        expected_power_change=None,
        confidence=0.6,
        uncertainty=0.4,
        horizon=PredictionHorizon.LONG_TERM,
    )

    restored = PredictionResult.model_validate_json(result.model_dump_json())

    assert restored == result


def test_candidate_identity_is_preserved():
    candidate = _candidate()
    result = _ContractPredictor().predict(_context(), candidate)

    assert result.candidate_id == candidate.id


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_prediction_confidence_validation_rejects_out_of_range(value: float):
    with pytest.raises(ValidationError):
        PredictionResult(
            candidate_id="candidate-confidence",
            confidence=value,
            uncertainty=0.5,
            horizon=PredictionHorizon.IMMEDIATE,
        )


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_prediction_uncertainty_validation_rejects_out_of_range(value: float):
    with pytest.raises(ValidationError):
        PredictionResult(
            candidate_id="candidate-uncertainty",
            confidence=0.5,
            uncertainty=value,
            horizon=PredictionHorizon.IMMEDIATE,
        )


@pytest.mark.parametrize(
    ("horizon", "serialized"),
    [
        (PredictionHorizon.IMMEDIATE, "immediate"),
        (PredictionHorizon.SHORT_TERM, "short_term"),
        (PredictionHorizon.LONG_TERM, "long_term"),
    ],
)
def test_prediction_horizon_serializes_with_stable_values(
    horizon: PredictionHorizon,
    serialized: str,
):
    result = PredictionResult(
        candidate_id="candidate-horizon",
        confidence=0.5,
        uncertainty=0.5,
        horizon=horizon,
    )

    assert result.horizon.value == serialized
    assert f'"horizon":"{serialized}"' in result.model_dump_json()


def test_outcome_predictor_interface_accepts_context_and_candidate():
    predictor: OutcomePredictor = _ContractPredictor()

    result = predictor.predict(_context(), _candidate())

    assert isinstance(result, PredictionResult)


def test_test_contract_predictor_is_deterministic():
    predictor: OutcomePredictor = _ContractPredictor()
    context = _context()
    candidate = _candidate()

    first = predictor.predict(context, candidate)
    second = predictor.predict(context, candidate)

    assert first == second


def test_test_contract_predictor_does_not_fabricate_expected_gain():
    candidate = _candidate(expected_gain=0.075)
    result = _ContractPredictor().predict(_context(), candidate)

    assert result.expected_reward_change == candidate.expected_gain
    assert result.expected_hashrate_change is None
    assert result.expected_power_change is None


def test_prediction_does_not_mutate_candidate_or_context_sources():
    predictor: OutcomePredictor = _ContractPredictor()
    context = _context()
    candidate = _candidate()

    candidate_before = candidate.model_dump()
    context_before = context.model_dump()
    evidence_before = context.evidence[0].model_dump()
    claim_before = context.claims[0].model_dump()
    hypothesis_before = context.hypotheses[0].model_dump()

    predictor.predict(context, candidate)

    assert candidate.model_dump() == candidate_before
    assert context.model_dump() == context_before
    assert context.evidence[0].model_dump() == evidence_before
    assert context.claims[0].model_dump() == claim_before
    assert context.hypotheses[0].model_dump() == hypothesis_before


def test_prediction_boundary_has_no_execution_methods():
    candidate = _candidate()
    result = _ContractPredictor().predict(_context(), candidate)

    for value in (candidate, result):
        assert not hasattr(value, "execute")
        assert not hasattr(value, "apply")
        assert not hasattr(value, "control")


def test_future_control_remains_metadata_only():
    candidate = CandidateAction(
        id="future-control-metadata",
        action_type=ActionType.NO_ACTION,
        description="Metadata boundary only.",
        execution_category=ExecutionCategory.FUTURE_CONTROL,
    )

    assert candidate.execution_category is ExecutionCategory.FUTURE_CONTROL
    assert not hasattr(candidate, "execute")
    assert not hasattr(candidate, "apply")
    assert not hasattr(candidate, "control")



def test_production_prediction_boundary_contains_no_concrete_predictor_model():
    local_classes = {
        name
        for name, value in inspect.getmembers(predictor_module, inspect.isclass)
        if value.__module__ == predictor_module.__name__
    }

    assert getattr(OutcomePredictor, "_is_protocol", False)
    assert local_classes == {
        "OutcomePredictor",
        "PredictionHorizon",
        "PredictionResult",
    }


def test_prediction_boundary_imports_no_external_model_or_execution_client():
    source = inspect.getsource(predictor_module).lower()

    forbidden_dependencies = (
        "openai",
        "anthropic",
        "httpx",
        "requests",
        "subprocess",
        "pynvml",
        "sklearn",
        "tensorflow",
        "torch",
    )
    assert all(dependency not in source for dependency in forbidden_dependencies)

def test_phase_one_contracts_remain_compatible():
    candidate = CandidateAction(
        id="phase-1",
        action_type=ActionType.NO_ACTION,
        description="No action",
        execution_category=ExecutionCategory.OBSERVATION_ONLY,
    )
    result = DecisionResult(
        decision_id="phase-1-result",
        state="proposed",
        selected_action=candidate,
        explanation="Compatible.",
    )

    assert result.selected_action == candidate


def test_phase_two_lifecycle_remains_compatible():
    assert DecisionState.DETECTED.value == "detected"
    assert can_transition(DecisionState.DETECTED, DecisionState.ANALYZING)


def test_phase_three_context_remains_compatible():
    context = _context()

    assert context.evidence
    assert context.claims
    assert context.hypotheses


def test_phase_four_candidate_generator_remains_compatible():
    candidates = CandidateGenerator().generate(_context())

    assert [candidate.action_type for candidate in candidates] == [
        ActionType.NO_ACTION,
        ActionType.INVESTIGATE_PERFORMANCE,
    ]


def test_phase_five_policy_contracts_remain_compatible():
    policy = DecisionPolicy(
        minimum_confidence=0.0,
        maximum_risk=1.0,
        minimum_expected_gain=0.0,
        allowed_execution_categories=[ExecutionCategory.OBSERVATION_ONLY],
        required_evidence_types=[EvidenceType.MEASURED],
    )
    result = evaluate_policy(policy, _candidate(), _context())

    assert result == PolicyResult(allowed=True, violations=[])
