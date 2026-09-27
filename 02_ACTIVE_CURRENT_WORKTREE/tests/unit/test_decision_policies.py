from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

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
    PolicyResult,
    PolicyViolation,
    evaluate_policy,
)
from mining_guardian.agent.decision.lifecycle import DecisionState, can_transition
from mining_guardian.agent.temporal import FreshnessLevel


def _evidence(
    domain: str = "performance",
    *,
    evidence_type: EvidenceType = EvidenceType.MEASURED,
) -> EvidenceItem:
    return EvidenceItem(
        id=f"evidence-{domain}-{evidence_type.value}",
        evidence_type=evidence_type,
        source="policy-test",
        value={"condition": domain},
        observed_at=datetime(2026, 9, 17, tzinfo=UTC),
        freshness=FreshnessLevel.FRESH,
        reliability=Reliability.HIGH,
        metadata={"decision_domain": domain},
    )


def _supported_context(
    domain: str = "performance",
    *,
    evidence_type: EvidenceType = EvidenceType.MEASURED,
    claim_status: ClaimStatus = ClaimStatus.SUPPORTED,
    hypothesis_status: HypothesisStatus = HypothesisStatus.SUPPORTED,
    missing_evidence_ids: list[str] | None = None,
) -> DecisionContext:
    evidence = _evidence(domain, evidence_type=evidence_type)
    claim = Claim(
        id=f"claim-{domain}",
        statement=f"{domain} condition is supported.",
        claim_type=ClaimType.OBSERVATION,
        supporting_evidence_ids=[evidence.id],
        confidence=Confidence.HIGH,
        status=claim_status,
    )
    hypothesis = Hypothesis(
        id=f"hypothesis-{domain}",
        statement=f"{domain} condition warrants evaluation.",
        supporting_evidence_ids=[evidence.id],
        missing_evidence_ids=list(missing_evidence_ids or []),
        confidence=Confidence.MEDIUM,
        status=hypothesis_status,
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
    action_type: ActionType = ActionType.INVESTIGATE_PERFORMANCE,
    *,
    confidence: float = 0.8,
    risk_score: float = 0.2,
    expected_gain: float = 0.05,
    execution_category: ExecutionCategory = ExecutionCategory.OBSERVATION_ONLY,
) -> CandidateAction:
    return CandidateAction(
        id=f"candidate-{action_type.value}",
        action_type=action_type,
        description=f"Candidate {action_type.value}",
        execution_category=execution_category,
        expected_gain=expected_gain,
        confidence=confidence,
        risk_score=risk_score,
        transition_cost=0.0,
        reversible=True,
    )


def _policy(
    *,
    minimum_confidence: float = 0.75,
    maximum_risk: float = 0.25,
    minimum_expected_gain: float = 0.03,
    allowed_execution_categories: list[ExecutionCategory] | None = None,
    required_evidence_types: list[EvidenceType] | None = None,
) -> DecisionPolicy:
    return DecisionPolicy(
        minimum_confidence=minimum_confidence,
        maximum_risk=maximum_risk,
        minimum_expected_gain=minimum_expected_gain,
        allowed_execution_categories=(
            [ExecutionCategory.OBSERVATION_ONLY]
            if allowed_execution_categories is None
            else allowed_execution_categories
        ),
        required_evidence_types=(
            [EvidenceType.MEASURED]
            if required_evidence_types is None
            else required_evidence_types
        ),
    )


def test_valid_decision_policy_construction_and_serialization():
    policy = _policy()
    restored = DecisionPolicy.model_validate_json(policy.model_dump_json())

    assert restored == policy
    assert restored.allowed_execution_categories == [ExecutionCategory.OBSERVATION_ONLY]
    assert restored.required_evidence_types == [EvidenceType.MEASURED]


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_invalid_minimum_confidence_is_rejected(value: float):
    with pytest.raises(ValidationError):
        _policy(minimum_confidence=value)


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_invalid_maximum_risk_is_rejected(value: float):
    with pytest.raises(ValidationError):
        _policy(maximum_risk=value)


def test_negative_minimum_expected_gain_is_rejected():
    with pytest.raises(ValidationError):
        _policy(minimum_expected_gain=-0.01)


def test_candidate_at_minimum_confidence_is_accepted_when_other_rules_pass():
    result = evaluate_policy(
        _policy(minimum_confidence=0.8),
        _candidate(confidence=0.8),
        _supported_context(),
    )

    assert result == PolicyResult(allowed=True, violations=[])


def test_candidate_below_minimum_confidence_is_rejected():
    result = evaluate_policy(
        _policy(minimum_confidence=0.8),
        _candidate(confidence=0.79),
        _supported_context(),
    )

    assert PolicyViolation.CONFIDENCE_BELOW_MINIMUM.value in result.violations
    assert not result.allowed


def test_candidate_at_maximum_risk_is_accepted_when_other_rules_pass():
    result = evaluate_policy(
        _policy(maximum_risk=0.2),
        _candidate(risk_score=0.2),
        _supported_context(),
    )

    assert result.allowed
    assert result.violations == []


def test_candidate_above_maximum_risk_is_rejected():
    result = evaluate_policy(
        _policy(maximum_risk=0.2),
        _candidate(risk_score=0.21),
        _supported_context(),
    )

    assert PolicyViolation.RISK_ABOVE_MAXIMUM.value in result.violations
    assert not result.allowed


def test_candidate_satisfying_minimum_expected_gain_is_accepted():
    result = evaluate_policy(
        _policy(minimum_expected_gain=0.05),
        _candidate(expected_gain=0.05),
        _supported_context(),
    )

    assert result.allowed


def test_non_no_action_below_minimum_expected_gain_is_rejected():
    result = evaluate_policy(
        _policy(minimum_expected_gain=0.05),
        _candidate(expected_gain=0.04),
        _supported_context(),
    )

    assert PolicyViolation.EXPECTED_GAIN_BELOW_MINIMUM.value in result.violations
    assert not result.allowed


def test_no_action_is_not_rejected_for_zero_expected_gain():
    candidate = _candidate(
        ActionType.NO_ACTION,
        confidence=0.8,
        expected_gain=0.0,
    )
    result = evaluate_policy(
        _policy(minimum_expected_gain=0.5),
        candidate,
        DecisionContext(evidence=[_evidence()]),
    )

    assert PolicyViolation.EXPECTED_GAIN_BELOW_MINIMUM.value not in result.violations
    assert result.allowed


def test_allowed_execution_category_passes():
    result = evaluate_policy(
        _policy(
            allowed_execution_categories=[
                ExecutionCategory.OBSERVATION_ONLY,
                ExecutionCategory.SIMULATION_ONLY,
            ]
        ),
        _candidate(execution_category=ExecutionCategory.SIMULATION_ONLY),
        _supported_context(),
    )

    assert result.allowed


def test_disallowed_execution_category_is_rejected():
    result = evaluate_policy(
        _policy(allowed_execution_categories=[ExecutionCategory.OBSERVATION_ONLY]),
        _candidate(execution_category=ExecutionCategory.RECOMMENDATION_ONLY),
        _supported_context(),
    )

    assert PolicyViolation.EXECUTION_CATEGORY_NOT_ALLOWED.value in result.violations
    assert not result.allowed


def test_future_control_remains_metadata_only():
    candidate = _candidate(execution_category=ExecutionCategory.FUTURE_CONTROL)
    result = evaluate_policy(
        _policy(allowed_execution_categories=[ExecutionCategory.FUTURE_CONTROL]),
        candidate,
        _supported_context(),
    )

    assert result.allowed
    assert candidate.execution_category is ExecutionCategory.FUTURE_CONTROL
    assert not hasattr(candidate, "execute")
    assert not hasattr(candidate, "apply")
    assert not hasattr(candidate, "control")


def test_required_evidence_type_present_passes():
    result = evaluate_policy(
        _policy(required_evidence_types=[EvidenceType.MEASURED]),
        _candidate(),
        _supported_context(evidence_type=EvidenceType.MEASURED),
    )

    assert result.allowed


def test_required_evidence_type_absent_is_rejected():
    result = evaluate_policy(
        _policy(required_evidence_types=[EvidenceType.HISTORICAL]),
        _candidate(),
        _supported_context(evidence_type=EvidenceType.MEASURED),
    )

    assert PolicyViolation.REQUIRED_EVIDENCE_MISSING.value in result.violations
    assert not result.allowed


@pytest.mark.parametrize(
    ("claim_status", "hypothesis_status", "missing_ids"),
    [
        (ClaimStatus.UNSUPPORTED, HypothesisStatus.SUPPORTED, []),
        (ClaimStatus.SUPPORTED, HypothesisStatus.REJECTED, []),
        (ClaimStatus.SUPPORTED, HypothesisStatus.SUPPORTED, ["missing-evidence"]),
    ],
)
def test_verifiably_unsupported_cognitive_basis_is_rejected(
    claim_status: ClaimStatus,
    hypothesis_status: HypothesisStatus,
    missing_ids: list[str],
):
    result = evaluate_policy(
        _policy(),
        _candidate(),
        _supported_context(
            claim_status=claim_status,
            hypothesis_status=hypothesis_status,
            missing_evidence_ids=missing_ids,
        ),
    )

    assert PolicyViolation.UNSUPPORTED_COGNITIVE_BASIS.value in result.violations
    assert not result.allowed


def test_policy_result_rejection_always_contains_violation():
    result = evaluate_policy(
        _policy(minimum_confidence=0.9),
        _candidate(confidence=0.5),
        _supported_context(),
    )

    assert not result.allowed
    assert result.violations


def test_policy_result_allowed_contains_no_violations():
    result = evaluate_policy(_policy(), _candidate(), _supported_context())

    assert result.allowed
    assert result.violations == []


def test_multiple_failures_are_collected_in_deterministic_order():
    result = evaluate_policy(
        _policy(
            minimum_confidence=0.9,
            maximum_risk=0.1,
            minimum_expected_gain=0.1,
            allowed_execution_categories=[ExecutionCategory.SIMULATION_ONLY],
            required_evidence_types=[EvidenceType.HISTORICAL],
        ),
        _candidate(
            confidence=0.1,
            risk_score=0.9,
            expected_gain=0.0,
            execution_category=ExecutionCategory.OBSERVATION_ONLY,
        ),
        DecisionContext(),
    )

    assert result.violations == [
        PolicyViolation.CONFIDENCE_BELOW_MINIMUM.value,
        PolicyViolation.RISK_ABOVE_MAXIMUM.value,
        PolicyViolation.EXPECTED_GAIN_BELOW_MINIMUM.value,
        PolicyViolation.EXECUTION_CATEGORY_NOT_ALLOWED.value,
        PolicyViolation.REQUIRED_EVIDENCE_MISSING.value,
        PolicyViolation.UNSUPPORTED_COGNITIVE_BASIS.value,
    ]


def test_same_inputs_produce_identical_policy_result():
    policy = _policy()
    candidate = _candidate()
    context = _supported_context()

    first = evaluate_policy(policy, candidate, context)
    second = evaluate_policy(policy, candidate, context)

    assert first == second


def test_policy_evaluation_does_not_mutate_sources():
    policy = _policy()
    candidate = _candidate()
    context = _supported_context()

    policy_before = policy.model_dump()
    candidate_before = candidate.model_dump()
    context_before = context.model_dump()
    evidence_before = context.evidence[0].model_dump()
    claim_before = context.claims[0].model_dump()
    hypothesis_before = context.hypotheses[0].model_dump()

    evaluate_policy(policy, candidate, context)

    assert policy.model_dump() == policy_before
    assert candidate.model_dump() == candidate_before
    assert context.model_dump() == context_before
    assert context.evidence[0].model_dump() == evidence_before
    assert context.claims[0].model_dump() == claim_before
    assert context.hypotheses[0].model_dump() == hypothesis_before


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
    context = _supported_context()

    assert isinstance(context, DecisionContext)
    assert context.evidence


def test_phase_four_candidate_generator_remains_compatible():
    candidates = CandidateGenerator().generate(_supported_context())

    assert [candidate.action_type for candidate in candidates] == [
        ActionType.NO_ACTION,
        ActionType.INVESTIGATE_PERFORMANCE,
    ]
