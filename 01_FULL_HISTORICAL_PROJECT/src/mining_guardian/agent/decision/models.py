from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class ActionType(StrEnum):
    NO_ACTION = "no_action"
    INVESTIGATE_PERFORMANCE = "investigate_performance"
    EVALUATE_EFFICIENCY = "evaluate_efficiency"
    EVALUATE_NETWORK = "evaluate_network"


class ExecutionCategory(StrEnum):
    OBSERVATION_ONLY = "observation_only"
    SIMULATION_ONLY = "simulation_only"
    RECOMMENDATION_ONLY = "recommendation_only"
    FUTURE_CONTROL = "future_control"


class CandidateAction(BaseModel):
    id: str
    action_type: ActionType
    description: str
    execution_category: ExecutionCategory
    expected_gain: float = 0.0
    confidence: float = 0.0
    risk_score: float = 0.0
    transition_cost: float = 0.0
    reversible: bool = True

    @field_validator("confidence", "risk_score")
    @classmethod
    def validate_probability(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("value must be between 0.0 and 1.0")
        return value

    @field_validator("expected_gain", "transition_cost")
    @classmethod
    def validate_non_negative(cls, value: float) -> float:
        if value < 0.0:
            raise ValueError("value must be non-negative")
        return value


class DecisionResult(BaseModel):
    decision_id: str
    state: str
    selected_action: CandidateAction | None = None
    alternatives: list[CandidateAction] = Field(default_factory=list)
    rejected_alternatives: list[CandidateAction] = Field(default_factory=list)
    confidence: float = 0.0
    explanation: str

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return value
