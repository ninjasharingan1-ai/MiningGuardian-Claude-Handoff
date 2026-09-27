from pydantic import BaseModel, Field

from .enums import Confidence, HypothesisStatus


class Hypothesis(BaseModel):
    id: str
    statement: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence_ids: list[str] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.LOW
    status: HypothesisStatus = HypothesisStatus.UNKNOWN
