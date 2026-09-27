from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from ..temporal import FreshnessLevel
from .enums import EvidenceType, Reliability


class EvidenceItem(BaseModel):
    id: str
    evidence_type: EvidenceType
    source: str
    value: dict[str, Any]
    observed_at: datetime | None = None
    freshness: FreshnessLevel = FreshnessLevel.UNKNOWN
    reliability: Reliability = Reliability.UNKNOWN
    limitations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
