from datetime import UTC, datetime

from pydantic import BaseModel, Field


class DecisionRecord(BaseModel):
    id: str
    context_summary: dict[str, object]
    evidence_ids: list[str]=Field(default_factory=list)
    claims: list[str]=Field(default_factory=list)
    hypotheses: list[str]=Field(default_factory=list)
    selected_next_step: str
    confidence: str
    limitations: list[str]=Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
