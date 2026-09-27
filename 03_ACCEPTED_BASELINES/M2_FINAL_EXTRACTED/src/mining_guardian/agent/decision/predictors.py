"""Typed prediction boundary for future decision outcome models."""

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, field_validator

from .context import DecisionContext
from .models import CandidateAction


class PredictionHorizon(StrEnum):
    """ADR-0006 prediction horizon metadata."""

    IMMEDIATE = "immediate"
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"


class PredictionResult(BaseModel):
    """Serializable prediction artifact without model or execution behavior."""

    candidate_id: str
    expected_reward_change: float | None = None
    expected_hashrate_change: float | None = None
    expected_power_change: float | None = None
    confidence: float
    uncertainty: float
    horizon: PredictionHorizon
    rationale: str | None = None

    @field_validator("confidence", "uncertainty")
    @classmethod
    def validate_probability(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("value must be between 0.0 and 1.0")
        return value


class OutcomePredictor(Protocol):
    """Replaceable interface for future outcome predictors."""

    def predict(
        self,
        context: DecisionContext,
        candidate: CandidateAction,
    ) -> PredictionResult:
        """Return a prediction artifact without mutating decision inputs."""
        ...
