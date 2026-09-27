from pydantic import BaseModel, Field

from .enums import ClaimStatus, ClaimType, Confidence


class Claim(BaseModel):
    id: str
    statement: str
    claim_type: ClaimType
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.UNKNOWN
    status: ClaimStatus = ClaimStatus.UNKNOWN
