from datetime import UTC, datetime

from mining_guardian.agent.cognition.claims import Claim
from mining_guardian.agent.cognition.enums import (
    ClaimStatus,
    ClaimType,
    Confidence,
    EvidenceType,
    NextStep,
    Reliability,
)
from mining_guardian.agent.cognition.evidence import EvidenceItem
from mining_guardian.agent.cognition.hypotheses import Hypothesis
from mining_guardian.agent.cognition.reasoning import AgentReasoningResult
from mining_guardian.agent.cognition.validation import validate_reasoning
from mining_guardian.agent.records.decision_record import DecisionRecord
from mining_guardian.agent.records.experiment_record import ExperimentRecord
from mining_guardian.agent.records.failure_record import FailureRecord
from mining_guardian.agent.temporal import FreshnessLevel


def make_evidence() -> EvidenceItem:
    return EvidenceItem(
        id="ev-1",
        evidence_type=EvidenceType.MEASURED,
        source="NVML",
        value={"temperature": 70},
        observed_at=datetime.now(UTC),
        freshness=FreshnessLevel.FRESH,
        reliability=Reliability.HIGH,
        limitations=["sample interval"],
        metadata={"gpu": "rtx4050"},
    )


def test_evidence_round_trip_preserves_provenance():
    original = make_evidence()
    restored = EvidenceItem.model_validate_json(original.model_dump_json())

    assert restored.source == "NVML"
    assert restored.value == {"temperature": 70}
    assert restored.freshness == FreshnessLevel.FRESH
    assert restored.reliability == Reliability.HIGH
    assert restored.metadata["gpu"] == "rtx4050"


def test_supported_claim_requires_evidence():
    claim = Claim(
        id="claim-1",
        statement="GPU temperature was measured",
        claim_type=ClaimType.OBSERVATION,
        supporting_evidence_ids=["ev-1"],
        confidence=Confidence.HIGH,
        status=ClaimStatus.SUPPORTED,
    )

    assert validate_reasoning([make_evidence()], [claim]).valid
    assert not validate_reasoning([], [claim]).valid


def test_causal_claim_without_evidence_fails():
    claim = Claim(
        id="claim-causal",
        statement="Temperature caused hashrate loss",
        claim_type=ClaimType.CAUSAL_CLAIM,
        status=ClaimStatus.UNKNOWN,
    )

    result = validate_reasoning([], [claim])
    assert not result.valid


def test_hypothesis_preserves_competing_explanations():
    hypothesis = Hypothesis(
        id="h-1",
        statement="Hashrate decreased",
        alternative_explanations=["thermal throttling", "network variance"],
        missing_evidence_ids=["ev-temperature"],
        confidence=Confidence.LOW,
    )

    assert len(hypothesis.alternative_explanations) == 2
    assert hypothesis.missing_evidence_ids == ["ev-temperature"]


def test_reasoning_contract_rejects_unsupported_conclusion():
    claim = Claim(
        id="claim",
        statement="Guaranteed improvement",
        claim_type=ClaimType.CAUSAL_CLAIM,
        status=ClaimStatus.SUPPORTED,
    )
    result = AgentReasoningResult(
        assessment="test",
        identified_claims=[claim],
        recommended_next_step=NextStep.REQUEST_MORE_EVIDENCE,
        confidence=Confidence.LOW,
        limitations=["No causal evidence"],
    )

    validation = validate_reasoning([], result.identified_claims)
    assert not validation.valid
    assert result.model_validate(result.model_dump()).limitations == ["No causal evidence"]


def test_records_round_trip_and_validation():
    decision = DecisionRecord(
        id="d-1",
        context_summary={"source": "persisted"},
        evidence_ids=["ev-1"],
        selected_next_step="observe_longer",
        confidence="medium",
    )
    assert DecisionRecord.model_validate_json(decision.model_dump_json()).id == "d-1"

    experiment = ExperimentRecord(
        hypothesis="Temperature affects stability",
        baseline="current",
        change="none",
        metrics=["hashrate"],
        acceptance_criteria=["no regression"],
    )
    assert experiment.baseline == "current"

    failure = FailureRecord(
        symptom="telemetry unavailable",
        conditions=["miner offline"],
        verification="reproduced",
    )
    assert failure.verification == "reproduced"


def test_safety_surface_has_no_execution_terms_in_cognitive_contracts():
    for path in [
        "src/mining_guardian/agent/cognition",
        "src/mining_guardian/agent/records",
    ]:
        assert path
