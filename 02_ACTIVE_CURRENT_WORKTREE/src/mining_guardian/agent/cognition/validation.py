from pydantic import BaseModel, Field

from ..temporal import FreshnessLevel
from .claims import Claim
from .enums import ClaimStatus, ClaimType
from .evidence import EvidenceItem


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def validate_reasoning(
    evidence: list[EvidenceItem], claims: list[Claim]
) -> ValidationResult:
    ids = {e.id for e in evidence}
    errors: list[str] = []
    warnings: list[str] = []

    for claim in claims:
        if (
            claim.status == ClaimStatus.SUPPORTED
            and not set(claim.supporting_evidence_ids) <= ids
        ):
            errors.append(f"claim {claim.id} lacks supporting evidence")
        if claim.claim_type == ClaimType.CAUSAL_CLAIM and not claim.supporting_evidence_ids:
            errors.append(f"causal claim {claim.id} lacks evidence")

    if any(e.freshness == FreshnessLevel.STALE for e in evidence):
        warnings.append("stale evidence present")

    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)
