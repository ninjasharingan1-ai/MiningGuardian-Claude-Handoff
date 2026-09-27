"""Normalized decision-input boundary for M2.2.2."""

from collections.abc import Sequence
from typing import Self

from pydantic import BaseModel, Field

from ..cognition.claims import Claim
from ..cognition.evidence import EvidenceItem
from ..cognition.hypotheses import Hypothesis
from ..models import AgentLesson, AgentWorkingMemory
from ..temporal import FreshnessLevel


class DecisionContext(BaseModel):
    """Stable cognitive snapshot consumed by future decision components."""

    evidence: list[EvidenceItem] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    freshness: FreshnessLevel = FreshnessLevel.UNKNOWN
    miner_freshness: FreshnessLevel = FreshnessLevel.UNKNOWN
    hardware_freshness: FreshnessLevel = FreshnessLevel.UNKNOWN
    historical_lessons: list[AgentLesson] = Field(default_factory=list)
    decision_constraints: list[str] = Field(default_factory=list)

    @classmethod
    def from_working_memory(
        cls,
        working_memory: AgentWorkingMemory,
        *,
        evidence: Sequence[EvidenceItem] = (),
        claims: Sequence[Claim] = (),
        hypotheses: Sequence[Hypothesis] = (),
        decision_constraints: Sequence[str] = (),
    ) -> Self:
        """Normalize existing cognitive inputs without inferring missing information."""

        world_state = working_memory.world_state
        return cls(
            evidence=list(evidence),
            claims=list(claims),
            hypotheses=list(hypotheses),
            freshness=world_state.freshness,
            miner_freshness=world_state.miner_freshness,
            hardware_freshness=world_state.hardware_freshness,
            historical_lessons=list(working_memory.relevant_lessons),
            decision_constraints=list(decision_constraints),
        )
