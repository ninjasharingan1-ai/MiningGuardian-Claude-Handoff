from datetime import UTC, datetime

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
    DecisionContext,
    DecisionResult,
    ExecutionCategory,
)
from mining_guardian.agent.decision.lifecycle import DecisionState, can_transition
from mining_guardian.agent.models import (
    AgentLesson,
    AgentWorkingMemory,
    DerivedWorldMetrics,
    MeasuredWorldFacts,
    MiningWorldState,
)
from mining_guardian.agent.temporal import FreshnessLevel


def _working_memory(*, with_lesson: bool = True) -> AgentWorkingMemory:
    lesson = AgentLesson(
        lesson_id="lesson-1",
        timestamp=datetime(2026, 9, 17, tzinfo=UTC),
        claim="Validated historical observation.",
        confidence=0.8,
    )
    return AgentWorkingMemory(
        world_state=MiningWorldState(
            timestamp=datetime(2026, 9, 17, tzinfo=UTC),
            freshness=FreshnessLevel.RECENT,
            miner_freshness=FreshnessLevel.FRESH,
            hardware_freshness=FreshnessLevel.STALE,
            facts=MeasuredWorldFacts(),
            derived=DerivedWorldMetrics(),
        ),
        relevant_lessons=[lesson] if with_lesson else [],
    )


def _evidence() -> EvidenceItem:
    return EvidenceItem(
        id="evidence-1",
        evidence_type=EvidenceType.MEASURED,
        source="test-source",
        value={"signal": "stable"},
        freshness=FreshnessLevel.FRESH,
        reliability=Reliability.HIGH,
    )


def _claim() -> Claim:
    return Claim(
        id="claim-1",
        statement="Observed condition is supported.",
        claim_type=ClaimType.OBSERVATION,
        supporting_evidence_ids=["evidence-1"],
        confidence=Confidence.HIGH,
        status=ClaimStatus.SUPPORTED,
    )


def _hypothesis() -> Hypothesis:
    return Hypothesis(
        id="hypothesis-1",
        statement="A supported explanation remains plausible.",
        supporting_evidence_ids=["evidence-1"],
        confidence=Confidence.MEDIUM,
        status=HypothesisStatus.ACTIVE,
    )


def test_decision_context_constructs_with_existing_cognitive_contracts():
    evidence = _evidence()
    claim = _claim()
    hypothesis = _hypothesis()

    context = DecisionContext(
        evidence=[evidence],
        claims=[claim],
        hypotheses=[hypothesis],
        freshness=FreshnessLevel.FRESH,
        miner_freshness=FreshnessLevel.FRESH,
        hardware_freshness=FreshnessLevel.FRESH,
        decision_constraints=["read_only"],
    )

    assert context.evidence == [evidence]
    assert context.claims == [claim]
    assert context.hypotheses == [hypothesis]
    assert context.decision_constraints == ["read_only"]


def test_from_working_memory_preserves_supplied_evidence_claims_and_hypotheses():
    evidence = _evidence()
    claim = _claim()
    hypothesis = _hypothesis()

    context = DecisionContext.from_working_memory(
        _working_memory(),
        evidence=[evidence],
        claims=[claim],
        hypotheses=[hypothesis],
    )

    assert context.evidence == [evidence]
    assert context.claims == [claim]
    assert context.hypotheses == [hypothesis]


def test_from_working_memory_preserves_existing_freshness_semantics():
    context = DecisionContext.from_working_memory(_working_memory())

    assert context.freshness is FreshnessLevel.RECENT
    assert context.miner_freshness is FreshnessLevel.FRESH
    assert context.hardware_freshness is FreshnessLevel.STALE


def test_from_working_memory_does_not_mutate_source_objects():
    working_memory = _working_memory()
    evidence = _evidence()
    claim = _claim()
    hypothesis = _hypothesis()

    working_memory_before = working_memory.model_dump()
    evidence_before = evidence.model_dump()
    claim_before = claim.model_dump()
    hypothesis_before = hypothesis.model_dump()

    DecisionContext.from_working_memory(
        working_memory,
        evidence=[evidence],
        claims=[claim],
        hypotheses=[hypothesis],
        decision_constraints=["read_only"],
    )

    assert working_memory.model_dump() == working_memory_before
    assert evidence.model_dump() == evidence_before
    assert claim.model_dump() == claim_before
    assert hypothesis.model_dump() == hypothesis_before


def test_decision_constraints_are_explicit_and_not_inferred():
    context = DecisionContext.from_working_memory(
        _working_memory(),
        decision_constraints=["simulation_only", "no_control"],
    )

    assert context.decision_constraints == ["simulation_only", "no_control"]


def test_historical_lessons_are_preserved_when_available():
    working_memory = _working_memory()

    context = DecisionContext.from_working_memory(working_memory)

    assert context.historical_lessons == working_memory.relevant_lessons


def test_historical_lessons_are_explicitly_empty_when_unavailable():
    context = DecisionContext.from_working_memory(_working_memory(with_lesson=False))

    assert context.historical_lessons == []


def test_unavailable_m22_cognitive_inputs_default_to_empty():
    context = DecisionContext.from_working_memory(_working_memory())

    assert context.evidence == []
    assert context.claims == []
    assert context.hypotheses == []
    assert context.decision_constraints == []


def test_phase_one_contracts_remain_compatible():
    action = CandidateAction(
        id="phase-1-action",
        action_type=ActionType.NO_ACTION,
        description="Preserve current state",
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
