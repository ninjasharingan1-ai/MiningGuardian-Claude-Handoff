"""Typed cognitive-domain models for M2.1/M2.1.1 shadow reasoning."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from ..enums import CapabilityState, SessionHealth, SessionState
from .temporal import (
    FreshnessLevel,
    GuardianSessionStatus,
    MinerReachability,
    ObservationOrigin,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class ProposalType(StrEnum):
    """Proposal classes permitted in M2.1 shadow mode."""

    NO_ACTION = "no_action"
    OBSERVE_LONGER = "observe_longer"
    REQUEST_MORE_EVIDENCE = "request_more_evidence"


class HypothesisStatus(StrEnum):
    ACTIVE = "active"
    SUPPORTED = "supported"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"


class ValidatorStatus(StrEnum):
    VALIDATED = "validated"
    REJECTED = "rejected"


class ExecutionStatus(StrEnum):
    NOT_EXECUTED_SHADOW = "not_executed_shadow"


class EpisodeType(StrEnum):
    SESSION_OBSERVATION = "session_observation"
    SHADOW_REASONING_CYCLE = "shadow_reasoning_cycle"


class WorldWorkloadState(BaseModel):
    """Latest measured miner facts for one algorithm workload."""

    raw_algorithm_name: str
    canonical_algorithm_id: str | None = None
    canonical_algorithm_name: str | None = None
    local_hashrate_hs: float | None = None
    accepted_shares: int | None = None
    rejected_shares: int | None = None
    invalid_shares: int | None = None
    miner_uptime_seconds: float | None = None
    gpu_errors: int | None = None
    device_ids: list[int] = Field(default_factory=list)


class WorldGPUState(BaseModel):
    """Latest measured hardware facts for one NVML GPU identity."""

    gpu_id: int
    miner: str | None = None
    algorithm_ids: list[str] = Field(default_factory=list)
    temperature_c: float | None = None
    utilization_gpu: float | None = None
    utilization_memory: float | None = None
    core_clock_mhz: float | None = None
    memory_clock_mhz: float | None = None
    power_w: float | None = None
    power_limit_w: float | None = None
    performance_state: str | None = None
    throttle_reasons: str | None = None
    capability_states: dict[str, CapabilityState] = Field(default_factory=dict)


class MeasuredWorldFacts(BaseModel):
    """Measured facts only; no inferred causal interpretation."""

    session_id: str | None = None
    session_start_time: datetime | None = None
    session_end_time: datetime | None = None
    guardian_session_status: GuardianSessionStatus = GuardianSessionStatus.UNKNOWN
    session_state: SessionState | None = None
    session_health: SessionHealth | None = None
    miner: str | None = None
    miner_version: str | None = None
    miner_reachability: MinerReachability = MinerReachability.UNKNOWN
    payout_coin: str | None = None
    workloads: list[WorldWorkloadState] = Field(default_factory=list)
    gpus: list[WorldGPUState] = Field(default_factory=list)


class DerivedWorldMetrics(BaseModel):
    """Deterministic metrics derived from measured facts."""

    session_age_seconds: float | None = Field(default=None, ge=0)
    session_duration_seconds: float | None = Field(default=None, ge=0)


class ContextValidity(BaseModel):
    """Deterministic guard metadata for future reasoning consumers."""

    is_current_state_usable: bool
    freshness: FreshnessLevel
    missing_required_signals: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MiningWorldState(BaseModel):
    """World snapshot with temporal provenance, facts, derivations, and unknowns."""

    timestamp: datetime
    observation_timestamp: datetime | None = None
    observation_origin: ObservationOrigin = ObservationOrigin.PERSISTED
    observation_age_seconds: float | None = Field(default=None, ge=0)
    freshness: FreshnessLevel = FreshnessLevel.UNKNOWN
    latest_miner_sample_at: datetime | None = None
    latest_hardware_sample_at: datetime | None = None
    miner_sample_age_seconds: float | None = Field(default=None, ge=0)
    hardware_sample_age_seconds: float | None = Field(default=None, ge=0)
    miner_freshness: FreshnessLevel = FreshnessLevel.UNKNOWN
    hardware_freshness: FreshnessLevel = FreshnessLevel.UNKNOWN
    facts: MeasuredWorldFacts
    derived: DerivedWorldMetrics
    missing_signals: list[str] = Field(default_factory=list)
    context_validity: ContextValidity = Field(
        default_factory=lambda: ContextValidity(
            is_current_state_usable=False,
            freshness=FreshnessLevel.UNKNOWN,
        )
    )

    @property
    def generated_at(self) -> datetime:
        """Compatibility-safe semantic alias for the generation timestamp."""

        return self.timestamp


class WorkloadWindowSummary(BaseModel):
    algorithm_id: str
    canonical_algorithm_name: str
    raw_algorithm_names: list[str] = Field(default_factory=list)
    device_ids: list[int] = Field(default_factory=list)
    sample_count: int = Field(ge=1)
    mean_hashrate_hs: float | None = None
    min_hashrate_hs: float | None = None
    max_hashrate_hs: float | None = None
    hashrate_slope_hs_per_second: float | None = None
    accepted_share_delta: int | None = None
    rejected_share_delta: int | None = None
    error_delta: int | None = None
    missing_hashrate_fraction: float = Field(ge=0, le=1)


class GPUWindowSummary(BaseModel):
    gpu_id: int
    sample_count: int = Field(ge=1)
    mean_temperature_c: float | None = None
    max_temperature_c: float | None = None
    mean_power_w: float | None = None
    mean_utilization_gpu: float | None = None
    missing_data_fraction: float = Field(ge=0, le=1)


class TelemetryWindowSummary(BaseModel):
    label: str
    start_time: datetime
    end_time: datetime
    latest_sample_at: datetime | None = None
    observation_origin: ObservationOrigin = ObservationOrigin.PERSISTED
    freshness: FreshnessLevel = FreshnessLevel.UNKNOWN
    session_status: GuardianSessionStatus = GuardianSessionStatus.UNKNOWN
    duration_seconds: float = Field(ge=0)
    miner_sample_count: int = Field(ge=0)
    hardware_sample_count: int = Field(ge=0)
    workloads: list[WorkloadWindowSummary] = Field(default_factory=list)
    gpus: list[GPUWindowSummary] = Field(default_factory=list)


class AgentHypothesis(BaseModel):
    hypothesis_id: str = Field(default_factory=lambda: _new_id("hypothesis"))
    statement: str
    evidence_for: list[str] = Field(default_factory=list)
    evidence_against: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    status: HypothesisStatus = HypothesisStatus.ACTIVE


class AgentProposal(BaseModel):
    proposal_type: ProposalType
    rationale: str
    expected_observation: str | None = None
    desired_evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    evaluation_horizon_seconds: int | None = Field(default=None, gt=0)


class AgentOutcome(BaseModel):
    """Future evaluation result; M2.1 defines the shape but does not generate outcomes."""

    outcome_id: str = Field(default_factory=lambda: _new_id("outcome"))
    decision_id: str
    timestamp: datetime
    observations: list[str] = Field(default_factory=list)
    evaluation_horizon_seconds: int | None = Field(default=None, gt=0)
    supports_proposal: bool | None = None


class LessonScope(BaseModel):
    session_id: str | None = None
    algorithm_id: str | None = None
    miner: str | None = None
    gpu_ids: list[int] = Field(default_factory=list)
    profile_name: str | None = None


class AgentLesson(BaseModel):
    lesson_id: str = Field(default_factory=lambda: _new_id("lesson"))
    timestamp: datetime
    claim: str
    supporting_observations: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    scope: LessonScope = Field(default_factory=LessonScope)
    algorithm_id: str | None = None
    hardware_identity: dict[str, Any] = Field(default_factory=dict)
    supersedes_lesson_id: str | None = None
    superseded_by_lesson_id: str | None = None


class AgentDecisionSummary(BaseModel):
    decision_id: str
    timestamp: datetime
    proposal_type: ProposalType
    confidence: float = Field(ge=0, le=1)
    validator_status: ValidatorStatus
    execution_status: ExecutionStatus


class AgentWorkingMemory(BaseModel):
    world_state: MiningWorldState
    context_windows: list[TelemetryWindowSummary] = Field(default_factory=list)
    active_hypotheses: list[AgentHypothesis] = Field(default_factory=list)
    recent_decisions: list[AgentDecisionSummary] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    relevant_lessons: list[AgentLesson] = Field(default_factory=list)


class AgentReasoningResult(BaseModel):
    hypotheses: list[AgentHypothesis] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    proposal: AgentProposal
    confidence: float = Field(ge=0, le=1)


class AgentDecision(BaseModel):
    decision_id: str = Field(default_factory=lambda: _new_id("decision"))
    timestamp: datetime
    session_id: str
    world_state_timestamp: datetime
    working_memory: AgentWorkingMemory
    hypotheses: list[AgentHypothesis] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    proposal: AgentProposal
    confidence: float = Field(ge=0, le=1)
    validator_status: ValidatorStatus
    execution_status: ExecutionStatus = ExecutionStatus.NOT_EXECUTED_SHADOW
    future_outcome_reference: str | None = None
    lesson_reference: str | None = None
    model_provider: str
    model_name: str
    agent_version: str

    def summary(self) -> AgentDecisionSummary:
        return AgentDecisionSummary(
            decision_id=self.decision_id,
            timestamp=self.timestamp,
            proposal_type=self.proposal.proposal_type,
            confidence=self.confidence,
            validator_status=self.validator_status,
            execution_status=self.execution_status,
        )


class AgentEpisode(BaseModel):
    episode_id: str = Field(default_factory=lambda: _new_id("episode"))
    timestamp: datetime
    session_id: str
    episode_type: EpisodeType
    algorithm_ids: list[str] = Field(default_factory=list)
    summary: str
    world_state_timestamp: datetime | None = None
    decision_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentCycleResult(BaseModel):
    working_memory: AgentWorkingMemory
    decision: AgentDecision
    episode: AgentEpisode
