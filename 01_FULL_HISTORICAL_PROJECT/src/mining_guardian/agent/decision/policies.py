"""Deterministic policy validation boundary for decision candidates."""

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from ..cognition.claims import Claim
from ..cognition.enums import ClaimStatus, EvidenceType, HypothesisStatus
from ..cognition.evidence import EvidenceItem
from ..cognition.hypotheses import Hypothesis
from ..cognition.validation import validate_reasoning
from .context import DecisionContext
from .models import ActionType, CandidateAction, ExecutionCategory

_DECISION_DOMAIN_METADATA_KEY = "decision_domain"

_DOMAIN_BY_ACTION: dict[ActionType, str] = {
    ActionType.INVESTIGATE_PERFORMANCE: "performance",
    ActionType.EVALUATE_EFFICIENCY: "efficiency",
    ActionType.EVALUATE_NETWORK: "network",
}


class PolicyViolation(StrEnum):
    """Stable policy violation identifiers for later explainability."""

    CONFIDENCE_BELOW_MINIMUM = "confidence_below_minimum"
    RISK_ABOVE_MAXIMUM = "risk_above_maximum"
    EXPECTED_GAIN_BELOW_MINIMUM = "expected_gain_below_minimum"
    EXECUTION_CATEGORY_NOT_ALLOWED = "execution_category_not_allowed"
    REQUIRED_EVIDENCE_MISSING = "required_evidence_missing"
    UNSUPPORTED_COGNITIVE_BASIS = "unsupported_cognitive_basis"


class DecisionPolicy(BaseModel):
    """Immutable-style configuration for candidate admissibility checks."""

    minimum_confidence: float
    maximum_risk: float
    minimum_expected_gain: float
    allowed_execution_categories: list[ExecutionCategory]
    required_evidence_types: list[EvidenceType]

    @field_validator("minimum_confidence", "maximum_risk")
    @classmethod
    def validate_probability(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("value must be between 0.0 and 1.0")
        return value

    @field_validator("minimum_expected_gain")
    @classmethod
    def validate_non_negative_gain(cls, value: float) -> float:
        if value < 0.0:
            raise ValueError("minimum_expected_gain must be non-negative")
        return value


class PolicyResult(BaseModel):
    """Serializable result of deterministic policy validation."""

    allowed: bool
    violations: list[str] = Field(default_factory=list)


def evaluate_policy(
    policy: DecisionPolicy,
    candidate: CandidateAction,
    context: DecisionContext,
) -> PolicyResult:
    """Validate candidate admissibility without scoring, ranking, or side effects."""

    violations: list[str] = []

    if candidate.confidence < policy.minimum_confidence:
        violations.append(PolicyViolation.CONFIDENCE_BELOW_MINIMUM.value)

    if candidate.risk_score > policy.maximum_risk:
        violations.append(PolicyViolation.RISK_ABOVE_MAXIMUM.value)

    if (
        candidate.action_type is not ActionType.NO_ACTION
        and candidate.expected_gain < policy.minimum_expected_gain
    ):
        violations.append(PolicyViolation.EXPECTED_GAIN_BELOW_MINIMUM.value)

    if candidate.execution_category not in policy.allowed_execution_categories:
        violations.append(PolicyViolation.EXECUTION_CATEGORY_NOT_ALLOWED.value)

    if not _has_required_evidence_types(policy, context.evidence):
        violations.append(PolicyViolation.REQUIRED_EVIDENCE_MISSING.value)

    if (
        candidate.action_type is not ActionType.NO_ACTION
        and not _has_supported_cognitive_basis(candidate, context)
    ):
        violations.append(PolicyViolation.UNSUPPORTED_COGNITIVE_BASIS.value)

    return PolicyResult(allowed=not violations, violations=violations)


def _has_required_evidence_types(
    policy: DecisionPolicy,
    evidence: list[EvidenceItem],
) -> bool:
    available_types = {item.evidence_type for item in evidence}
    return set(policy.required_evidence_types) <= available_types


def _has_supported_cognitive_basis(
    candidate: CandidateAction,
    context: DecisionContext,
) -> bool:
    required_domain = _DOMAIN_BY_ACTION.get(candidate.action_type)
    if required_domain is None:
        return False

    evidence_by_id = {item.id: item for item in context.evidence}
    supported_claims = _supported_claims(context.evidence, context.claims)

    for hypothesis in context.hypotheses:
        if not _hypothesis_is_supported(hypothesis, evidence_by_id):
            continue

        hypothesis_evidence_ids = set(hypothesis.supporting_evidence_ids)
        for claim in supported_claims:
            shared_ids = hypothesis_evidence_ids.intersection(
                claim.supporting_evidence_ids
            )
            if any(
                evidence_by_id[evidence_id].metadata.get(
                    _DECISION_DOMAIN_METADATA_KEY
                )
                == required_domain
                for evidence_id in shared_ids
            ):
                return True

    return False


def _supported_claims(
    evidence: list[EvidenceItem],
    claims: list[Claim],
) -> list[Claim]:
    supported: list[Claim] = []
    for claim in claims:
        if claim.status is not ClaimStatus.SUPPORTED:
            continue
        if not claim.supporting_evidence_ids:
            continue
        if validate_reasoning(evidence, [claim]).valid:
            supported.append(claim)
    return supported


def _hypothesis_is_supported(
    hypothesis: Hypothesis,
    evidence_by_id: dict[str, EvidenceItem],
) -> bool:
    if hypothesis.status not in {
        HypothesisStatus.ACTIVE,
        HypothesisStatus.SUPPORTED,
    }:
        return False
    if not hypothesis.supporting_evidence_ids:
        return False
    if hypothesis.missing_evidence_ids:
        return False
    return set(hypothesis.supporting_evidence_ids) <= evidence_by_id.keys()
