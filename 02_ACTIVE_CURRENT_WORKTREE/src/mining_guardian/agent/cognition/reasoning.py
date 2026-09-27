from pydantic import BaseModel, Field

from .claims import Claim
from .enums import Confidence, NextStep
from .hypotheses import Hypothesis


class AgentReasoningResult(BaseModel):
    assessment: str
    identified_claims: list[Claim] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    recommended_next_step: NextStep
    confidence: Confidence
    limitations: list[str] = Field(default_factory=list)
