from datetime import UTC, datetime

import pytest

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
    DecisionResult,
    ExecutionCategory,
)
from mining_guardian.agent.decision.lifecycle import DecisionState, can_transition
from mining_guardian.agent.models import (
    AgentWorkingMemory,
    DerivedWorldMetrics,
    MeasuredWorldFacts,
    MiningWorldState,
    WorldGPUState,
    WorldWorkloadState,
)
from mining_guardian.agent.temporal import FreshnessLevel


def _raw_working_memory() -> AgentWorkingMemory:
    return AgentWorkingMemory(
        world_state=MiningWorldState(
            timestamp=datetime(2026, 9, 17, tzinfo=UTC),
            freshness=FreshnessLevel.FRESH,
            miner_freshness=FreshnessLevel.FRESH,
            hardware_freshness=FreshnessLevel.FRESH,
            facts=MeasuredWorldFacts(
                workloads=[
                    WorldWorkloadState(
                        raw_algorithm_name="pearlhash",
                        canonical_algorithm_id="pearlpow",
                        canonical_algorithm_name="PearlPow",
                        local_hashrate_hs=1.0,
                        accepted_shares=0,
                        rejected_shares=100,
                    )
                ],
                gpus=[
                    WorldGPUState(
                        gpu_id=0,
                        temperature_c=99.0,
                        power_w=999.0,
                    )
                ],
            ),
            derived=DerivedWorldMetrics(),
        )
    )


def _cognitive_chain(
    domain: str,
    *,
    claim_status: ClaimStatus = ClaimStatus.SUPPORTED,
    hypothesis_status: HypothesisStatus = HypothesisStatus.SUPPORTED,
    missing_evidence_ids: list[str] | None = None,
) -> tuple[EvidenceItem, Claim, Hypothesis]:
    evidence_id = f"evidence-{domain}"
    evidence = EvidenceItem(
        id=evidence_id,
        evidence_type=EvidenceType.MEASURED,
        source="cognitive-test",
        value={"observation": f"{domain} condition"},
        freshness=FreshnessLevel.FRESH,
        reliability=Reliability.HIGH,
        metadata={"decision_domain": domain},
    )
    claim = Claim(
        id=f"claim-{domain}",
        statement=f"A {domain} condition is supported.",
        claim_type=ClaimType.OBSERVATION,
        supporting_evidence_ids=[evidence_id],
        confidence=Confidence.HIGH,
        status=claim_status,
    )
    hypothesis = Hypothesis(
        id=f"hypothesis-{domain}",
        statement=f"The {domain} condition warrants evaluation.",
        supporting_evidence_ids=[evidence_id],
        missing_evidence_ids=list(missing_evidence_ids or []),
        confidence=Confidence.MEDIUM,
        status=hypothesis_status,
    )
    return evidence, claim, hypothesis


def _context_for_domain(domain: str) -> DecisionContext:
    evidence, claim, hypothesis = _cognitive_chain(domain)
    return DecisionContext(
        evidence=[evidence],
        claims=[claim],
        hypotheses=[hypothesis],
        freshness=FreshnessLevel.FRESH,
        miner_freshness=FreshnessLevel.FRESH,
        hardware_freshness=FreshnessLevel.FRESH,
    )


def _types(context: DecisionContext) -> list[ActionType]:
    return [candidate.action_type for candidate in CandidateGenerator().generate(context)]


def test_empty_cognitive_context_produces_safe_no_action():
    assert _types(DecisionContext()) == [ActionType.NO_ACTION]


@pytest.mark.parametrize(
    "forbidden_action",
    [
        ActionType.INVESTIGATE_PERFORMANCE,
        ActionType.EVALUATE_EFFICIENCY,
        ActionType.EVALUATE_NETWORK,
    ],
)
def test_raw_telemetry_alone_cannot_create_actionable_candidate(
    forbidden_action: ActionType,
):
    context = DecisionContext.from_working_memory(_raw_working_memory())

    assert forbidden_action not in _types(context)
    assert _types(context) == [ActionType.NO_ACTION]


@pytest.mark.parametrize(
    ("domain", "expected_action"),
    [
        ("performance", ActionType.INVESTIGATE_PERFORMANCE),
        ("efficiency", ActionType.EVALUATE_EFFICIENCY),
        ("network", ActionType.EVALUATE_NETWORK),
    ],
)
def test_supported_cognitive_chain_generates_expected_candidate(
    domain: str,
    expected_action: ActionType,
):
    action_types = _types(_context_for_domain(domain))

    assert ActionType.NO_ACTION in action_types
    assert expected_action in action_types


def test_unsupported_claim_does_not_generate_actionable_candidate():
    evidence, claim, hypothesis = _cognitive_chain(
        "performance",
        claim_status=ClaimStatus.UNSUPPORTED,
    )
    context = DecisionContext(
        evidence=[evidence],
        claims=[claim],
        hypotheses=[hypothesis],
    )

    assert _types(context) == [ActionType.NO_ACTION]


@pytest.mark.parametrize(
    "hypothesis_status",
    [HypothesisStatus.REJECTED, HypothesisStatus.UNKNOWN],
)
def test_unsupported_hypothesis_does_not_generate_actionable_candidate(
    hypothesis_status: HypothesisStatus,
):
    evidence, claim, hypothesis = _cognitive_chain(
        "efficiency",
        hypothesis_status=hypothesis_status,
    )
    context = DecisionContext(
        evidence=[evidence],
        claims=[claim],
        hypotheses=[hypothesis],
    )

    assert _types(context) == [ActionType.NO_ACTION]


def test_hypothesis_with_missing_evidence_does_not_generate_candidate():
    evidence, claim, hypothesis = _cognitive_chain(
        "network",
        missing_evidence_ids=["missing-network-evidence"],
    )
    context = DecisionContext(
        evidence=[evidence],
        claims=[claim],
        hypotheses=[hypothesis],
    )

    assert _types(context) == [ActionType.NO_ACTION]


def test_unlinked_claim_and_hypothesis_do_not_generate_candidate():
    evidence, claim, _ = _cognitive_chain("performance")
    other_evidence, _, hypothesis = _cognitive_chain("efficiency")
    context = DecisionContext(
        evidence=[evidence, other_evidence],
        claims=[claim],
        hypotheses=[hypothesis],
    )

    assert _types(context) == [ActionType.NO_ACTION]


def test_unknown_or_missing_domain_metadata_does_not_infer_candidate():
    evidence, claim, hypothesis = _cognitive_chain("unknown-domain")
    context = DecisionContext(
        evidence=[evidence],
        claims=[claim],
        hypotheses=[hypothesis],
    )

    assert _types(context) == [ActionType.NO_ACTION]


def test_generated_actions_use_typed_non_executing_contracts():
    candidates = CandidateGenerator().generate(_context_for_domain("network"))

    assert all(isinstance(candidate.action_type, ActionType) for candidate in candidates)
    assert all(
        candidate.execution_category is ExecutionCategory.OBSERVATION_ONLY
        for candidate in candidates
    )
    assert all(
        candidate.execution_category is not ExecutionCategory.FUTURE_CONTROL
        for candidate in candidates
    )


def test_generated_numeric_fields_are_explicit_neutral_defaults():
    candidates = CandidateGenerator().generate(_context_for_domain("performance"))

    for candidate in candidates:
        assert candidate.expected_gain == 0.0
        assert candidate.confidence == 0.0
        assert candidate.risk_score == 0.0
        assert candidate.transition_cost == 0.0


def test_generation_order_is_stable_and_not_score_based():
    evidence_p, claim_p, hypothesis_p = _cognitive_chain("performance")
    evidence_e, claim_e, hypothesis_e = _cognitive_chain("efficiency")
    evidence_n, claim_n, hypothesis_n = _cognitive_chain("network")
    context = DecisionContext(
        evidence=[evidence_n, evidence_p, evidence_e],
        claims=[claim_e, claim_n, claim_p],
        hypotheses=[hypothesis_n, hypothesis_p, hypothesis_e],
    )
    generator = CandidateGenerator()

    first = generator.generate(context)
    second = generator.generate(context)

    assert first == second
    assert [candidate.action_type for candidate in first] == [
        ActionType.NO_ACTION,
        ActionType.INVESTIGATE_PERFORMANCE,
        ActionType.EVALUATE_EFFICIENCY,
        ActionType.EVALUATE_NETWORK,
    ]


def test_generation_does_not_mutate_cognitive_source_objects():
    context = _context_for_domain("efficiency")
    context_before = context.model_dump()
    evidence_before = context.evidence[0].model_dump()
    claim_before = context.claims[0].model_dump()
    hypothesis_before = context.hypotheses[0].model_dump()

    CandidateGenerator().generate(context)

    assert context.model_dump() == context_before
    assert context.evidence[0].model_dump() == evidence_before
    assert context.claims[0].model_dump() == claim_before
    assert context.hypotheses[0].model_dump() == hypothesis_before


def test_phase_one_contracts_remain_compatible():
    action = CandidateAction(
        id="phase-1-action",
        action_type=ActionType.NO_ACTION,
        description="No action",
        execution_category=ExecutionCategory.OBSERVATION_ONLY,
    )
    result = DecisionResult(
        decision_id="phase-1-result",
        state="proposed",
        selected_action=action,
        explanation="Phase 1 remains compatible.",
    )

    assert result.selected_action == action


def test_phase_two_contracts_remain_compatible():
    assert DecisionState.DETECTED.value == "detected"
    assert can_transition(DecisionState.DETECTED, DecisionState.ANALYZING)


def test_phase_three_decision_context_remains_compatible():
    context = DecisionContext.from_working_memory(_raw_working_memory())

    assert context.evidence == []
    assert context.claims == []
    assert context.hypotheses == []
