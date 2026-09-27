"""Deterministic ADR-0006 Decision Utility Scoring Engine."""

from pydantic import BaseModel, field_validator

from .models import CandidateAction
from .predictors import PredictionResult


class DecisionScore(BaseModel):
    """Serializable output of ADR-0006 candidate scoring."""

    candidate_id: str
    benefit: float
    confidence: float
    risk: float
    action_cost: float
    uncertainty: float
    utility_score: float

    @field_validator("confidence", "risk", "uncertainty")
    @classmethod
    def validate_probability(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("value must be between 0.0 and 1.0")
        return value

    @field_validator("action_cost")
    @classmethod
    def validate_non_negative_action_cost(cls, value: float) -> float:
        if value < 0.0:
            raise ValueError("action_cost must be non-negative")
        return value


class DecisionScorer:
    """Apply only the ADR-0006 Decision Utility Score formula."""

    def score(
        self,
        candidate: CandidateAction,
        prediction: PredictionResult,
    ) -> DecisionScore:
        """Return a pure deterministic score for a policy-approved candidate."""

        if prediction.candidate_id != candidate.id:
            raise ValueError("prediction candidate_id must match candidate id")

        benefit = (
            prediction.expected_reward_change
            if prediction.expected_reward_change is not None
            else candidate.expected_gain
        )
        confidence = prediction.confidence
        risk = candidate.risk_score
        action_cost = candidate.transition_cost
        uncertainty = prediction.uncertainty
        utility_score = (benefit * confidence) - (
            risk + action_cost + uncertainty
        )

        return DecisionScore(
            candidate_id=candidate.id,
            benefit=benefit,
            confidence=confidence,
            risk=risk,
            action_cost=action_cost,
            uncertainty=uncertainty,
            utility_score=utility_score,
        )
