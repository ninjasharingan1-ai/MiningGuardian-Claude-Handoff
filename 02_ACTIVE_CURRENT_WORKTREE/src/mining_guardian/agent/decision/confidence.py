"""Deterministic decision-confidence assessment for M2.2.2."""

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from ..cognition.enums import Reliability
from ..temporal import FreshnessLevel
from .context import DecisionContext
from .predictors import PredictionResult


class ConfidenceLimitation(StrEnum):
    """Stable identifiers describing unavailable or weak confidence inputs."""

    NO_EVIDENCE = "no_evidence"
    UNKNOWN_CONTEXT_FRESHNESS = "unknown_context_freshness"
    STALE_CONTEXT_FRESHNESS = "stale_context_freshness"
    UNKNOWN_EVIDENCE_RELIABILITY = "unknown_evidence_reliability"
    UNKNOWN_EVIDENCE_FRESHNESS = "unknown_evidence_freshness"
    STALE_EVIDENCE = "stale_evidence"
    NUMERIC_EVIDENCE_QUALITY_UNAVAILABLE = "numeric_evidence_quality_unavailable"
    NUMERIC_FRESHNESS_FACTOR_UNAVAILABLE = "numeric_freshness_factor_unavailable"


class EvidenceConfidenceInput(BaseModel):
    """Existing evidence confidence semantics preserved without remapping."""

    evidence_id: str
    reliability: Reliability
    freshness: FreshnessLevel


class DecisionConfidenceResult(BaseModel):
    """Serializable component-level confidence assessment."""

    candidate_id: str
    evidence_inputs: list[EvidenceConfidenceInput] = Field(default_factory=list)
    context_freshness: FreshnessLevel
    miner_freshness: FreshnessLevel
    hardware_freshness: FreshnessLevel
    prediction_reliability: float
    overall_confidence: float | None = None
    limitations: list[ConfidenceLimitation] = Field(default_factory=list)

    @field_validator("prediction_reliability")
    @classmethod
    def validate_prediction_reliability(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("prediction_reliability must be between 0.0 and 1.0")
        return value


class DecisionConfidenceEngine:
    """Assess confidence inputs without scoring, ranking, or numeric remapping."""

    def evaluate(
        self,
        context: DecisionContext,
        prediction: PredictionResult,
    ) -> DecisionConfidenceResult:
        """Return deterministic confidence components from approved contracts."""

        evidence_inputs = [
            EvidenceConfidenceInput(
                evidence_id=item.id,
                reliability=item.reliability,
                freshness=item.freshness,
            )
            for item in context.evidence
        ]

        limitations: list[ConfidenceLimitation] = []
        if not evidence_inputs:
            limitations.append(ConfidenceLimitation.NO_EVIDENCE)

        if context.freshness is FreshnessLevel.UNKNOWN:
            limitations.append(ConfidenceLimitation.UNKNOWN_CONTEXT_FRESHNESS)
        elif context.freshness is FreshnessLevel.STALE:
            limitations.append(ConfidenceLimitation.STALE_CONTEXT_FRESHNESS)

        if any(
            item.reliability is Reliability.UNKNOWN for item in evidence_inputs
        ):
            limitations.append(ConfidenceLimitation.UNKNOWN_EVIDENCE_RELIABILITY)

        if any(
            item.freshness is FreshnessLevel.UNKNOWN for item in evidence_inputs
        ):
            limitations.append(ConfidenceLimitation.UNKNOWN_EVIDENCE_FRESHNESS)

        if any(
            item.freshness is FreshnessLevel.STALE for item in evidence_inputs
        ):
            limitations.append(ConfidenceLimitation.STALE_EVIDENCE)

        # ADR-0006 defines a multiplicative aggregate, but the current
        # evidence-reliability and freshness contracts are categorical and
        # intentionally provide no approved numeric mapping.
        limitations.extend(
            [
                ConfidenceLimitation.NUMERIC_EVIDENCE_QUALITY_UNAVAILABLE,
                ConfidenceLimitation.NUMERIC_FRESHNESS_FACTOR_UNAVAILABLE,
            ]
        )

        return DecisionConfidenceResult(
            candidate_id=prediction.candidate_id,
            evidence_inputs=evidence_inputs,
            context_freshness=context.freshness,
            miner_freshness=context.miner_freshness,
            hardware_freshness=context.hardware_freshness,
            prediction_reliability=prediction.confidence,
            overall_confidence=None,
            limitations=limitations,
        )
