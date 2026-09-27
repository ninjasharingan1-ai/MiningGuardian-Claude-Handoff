"""Shadow-only agent orchestration for M2.1."""

from datetime import datetime

from pydantic import ValidationError

from ..storage.agent_repository import AgentDecisionRepository, AgentEpisodeRepository
from .context import WorkingMemoryBuilder
from .gateway import ModelGateway
from .models import (
    AgentCycleResult,
    AgentDecision,
    AgentEpisode,
    AgentReasoningResult,
    EpisodeType,
    ExecutionStatus,
    ValidatorStatus,
)


class ShadowReasoningValidationError(RuntimeError):
    """Raised when a gateway returns reasoning that does not satisfy the typed contract."""


class ShadowSessionRequiredError(RuntimeError):
    """Raised when decision journaling is attempted without a persisted Guardian session."""


class ShadowMiningAgent:
    """Runs one auditable reasoning cycle and never executes a proposal."""

    AGENT_VERSION = "m2.1"

    def __init__(
        self,
        working_memory_builder: WorkingMemoryBuilder,
        model_gateway: ModelGateway,
        decision_repository: AgentDecisionRepository,
        episode_repository: AgentEpisodeRepository,
    ) -> None:
        self.working_memory_builder = working_memory_builder
        self.model_gateway = model_gateway
        self.decision_repository = decision_repository
        self.episode_repository = episode_repository

    def run_once(
        self,
        session_id: str | None = None,
        *,
        now: datetime | None = None,
    ) -> AgentCycleResult:
        working_memory = self.working_memory_builder.build(session_id, now=now)
        raw_reasoning = self.model_gateway.reason(working_memory)
        try:
            reasoning = AgentReasoningResult.model_validate(raw_reasoning.model_dump())
        except ValidationError as exc:
            raise ShadowReasoningValidationError(
                "Model gateway returned invalid structured reasoning."
            ) from exc

        persisted_session_id = working_memory.world_state.facts.session_id
        if persisted_session_id is None:
            raise ShadowSessionRequiredError(
                "Shadow decision journaling requires a persisted Guardian session."
            )

        timestamp = now or datetime.now()
        decision = AgentDecision(
            timestamp=timestamp,
            session_id=persisted_session_id,
            world_state_timestamp=working_memory.world_state.timestamp,
            working_memory=working_memory,
            hypotheses=reasoning.hypotheses,
            evidence=reasoning.evidence,
            missing_evidence=reasoning.missing_evidence,
            proposal=reasoning.proposal,
            confidence=reasoning.confidence,
            validator_status=ValidatorStatus.VALIDATED,
            execution_status=ExecutionStatus.NOT_EXECUTED_SHADOW,
            model_provider=self.model_gateway.provider_name,
            model_name=self.model_gateway.model_name,
            agent_version=self.AGENT_VERSION,
        )
        self.decision_repository.create(decision)

        algorithm_ids: list[str] = []
        for workload in working_memory.world_state.facts.workloads:
            algorithm_id = workload.canonical_algorithm_id
            if algorithm_id is not None:
                algorithm_ids.append(algorithm_id)
        episode = AgentEpisode(
            timestamp=timestamp,
            session_id=decision.session_id,
            episode_type=EpisodeType.SHADOW_REASONING_CYCLE,
            algorithm_ids=algorithm_ids,
            summary=(
                "Shadow reasoning cycle recorded; proposal was not executed."
            ),
            world_state_timestamp=working_memory.world_state.timestamp,
            decision_id=decision.decision_id,
            metadata={
                "proposal_type": decision.proposal.proposal_type.value,
                "execution_status": decision.execution_status.value,
            },
        )
        self.episode_repository.create(episode)
        return AgentCycleResult(
            working_memory=working_memory,
            decision=decision,
            episode=episode,
        )
