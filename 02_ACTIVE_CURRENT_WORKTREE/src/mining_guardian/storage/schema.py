from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AlgorithmDB(Base):
    __tablename__ = "algorithms"

    algorithm_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    underlying_asset: Mapped[str | None] = mapped_column(String(128), nullable=True)
    optimizer_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AlgorithmAliasDB(Base):
    __tablename__ = "algorithm_aliases"
    __table_args__ = (
        UniqueConstraint("scope_type", "scope_name", "alias_normalized", name="uq_algorithm_alias_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    algorithm_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("algorithms.algorithm_id"),
        nullable=False,
        index=True,
    )
    raw_alias: Mapped[str] = mapped_column(String(128), nullable=False)
    alias_normalized: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, default="alias")
    scope_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")


class SessionDB(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    miner: Mapped[str] = mapped_column(String(64), nullable=False, default="srbminer")
    gpu_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    algorithm_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    raw_algorithm_names_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    payout_coin: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="observe")
    health: Mapped[str] = mapped_column(String(32), nullable=False, default="healthy")


class HardwareSampleDB(Base):
    __tablename__ = "hardware_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.session_id"),
        nullable=False,
        index=True,
    )
    gpu_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    miner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    algorithm_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    utilization_gpu: Mapped[float | None] = mapped_column(Float, nullable=True)
    utilization_memory: Mapped[float | None] = mapped_column(Float, nullable=True)
    core_clock_mhz: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_clock_mhz: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_limit_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    performance_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    throttle_reasons: Mapped[str | None] = mapped_column(Text, nullable=True)
    capability_states_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class MinerSampleDB(Base):
    __tablename__ = "miner_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.session_id"),
        nullable=False,
        index=True,
    )
    miner: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_algorithm_name: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_algorithm_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("algorithms.algorithm_id"),
        nullable=False,
        index=True,
    )
    canonical_algorithm_name: Mapped[str] = mapped_column(String(128), nullable=False)
    local_hashrate_hs: Mapped[float | None] = mapped_column(Float, nullable=True)
    accepted_shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rejected_shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    invalid_shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    miner_uptime_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    gpu_errors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    device_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    raw_data_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class EventDB(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("sessions.session_id"),
        nullable=True,
        index=True,
    )
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    event_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)



class AgentEpisodeDB(Base):
    __tablename__ = "agent_episodes"

    episode_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.session_id"),
        nullable=False,
        index=True,
    )
    episode_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    algorithm_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    world_state_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    episode_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class AgentDecisionDB(Base):
    __tablename__ = "agent_decisions"

    decision_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.session_id"),
        nullable=False,
        index=True,
    )
    world_state_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    working_memory_json: Mapped[str] = mapped_column(Text, nullable=False)
    hypotheses_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    missing_evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    proposal_json: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    validator_status: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_status: Mapped[str] = mapped_column(String(64), nullable=False)
    future_outcome_reference: Mapped[str | None] = mapped_column(String(96), nullable=True)
    lesson_reference: Mapped[str | None] = mapped_column(String(96), nullable=True)
    model_provider: Mapped[str] = mapped_column(String(128), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(64), nullable=False)


class AgentLessonDB(Base):
    __tablename__ = "agent_lessons"

    lesson_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("sessions.session_id"),
        nullable=True,
        index=True,
    )
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_observations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    scope_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    algorithm_id: Mapped[str | None] = mapped_column(
        String(128),
        ForeignKey("algorithms.algorithm_id"),
        nullable=True,
        index=True,
    )
    hardware_identity_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    supersedes_lesson_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    superseded_by_lesson_id: Mapped[str | None] = mapped_column(String(96), nullable=True)


class DecisionEvaluationDB(Base):
    """Persist one Decision Engine evaluation.

    ``timestamp_iso`` is the authoritative timestamp reconstruction source.
    ``timestamp`` remains a convenience/query snapshot because SQLite's DateTime
    representation does not preserve timezone offsets.

    ``DecisionConfidenceDB.overall_confidence`` is the authoritative persisted
    Phase 9 aggregate confidence. ``confidence`` is a non-authoritative snapshot
    of an already-supplied decision-level confidence value.

    ``DecisionResult.explanation`` is persisted independently in
    ``result_explanation``. ``DecisionExplanationDB.explanation_json`` is the
    authoritative structured Phase 11 explanation artifact, while
    ``explanation_json`` is a non-authoritative snapshot only.
    """

    __tablename__ = "decision_evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        index=True,
        comment=(
            "Convenience/query snapshot only; timestamp_iso is authoritative for "
            "lossless DecisionEvaluationArtifacts.timestamp reconstruction."
        ),
    )
    timestamp_iso: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment=(
            "Authoritative ISO-8601 DecisionEvaluationArtifacts.timestamp value, "
            "preserving microseconds, naive/aware distinction, and UTC offset."
        ),
    )
    session_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("sessions.session_id"),
        nullable=True,
        index=True,
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    selected_candidate_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("decision_candidates.id"),
        nullable=True,
    )
    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment=(
            "Non-authoritative snapshot of an already-supplied decision-level "
            "confidence value; DecisionConfidenceDB.overall_confidence is authoritative."
        ),
    )
    result_explanation: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Authoritative persisted DecisionResult.explanation value.",
    )
    explanation_json: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment=(
            "Non-authoritative snapshot only; "
            "DecisionExplanationDB.explanation_json is authoritative."
        ),
    )

    candidates: Mapped[list["DecisionCandidateDB"]] = relationship(
        back_populates="decision_evaluation",
        foreign_keys="DecisionCandidateDB.decision_evaluation_id",
    )
    selected_candidate: Mapped["DecisionCandidateDB | None"] = relationship(
        foreign_keys=[selected_candidate_id],
        post_update=True,
    )
    rankings: Mapped[list["DecisionRankingDB"]] = relationship(
        back_populates="decision_evaluation",
        foreign_keys="DecisionRankingDB.decision_evaluation_id",
    )
    confidence_artifact: Mapped["DecisionConfidenceDB | None"] = relationship(
        back_populates="decision_evaluation",
        uselist=False,
    )
    explanation: Mapped["DecisionExplanationDB | None"] = relationship(
        back_populates="decision_evaluation",
        uselist=False,
    )


class DecisionCandidateDB(Base):
    __tablename__ = "decision_candidates"
    __table_args__ = (
        UniqueConstraint(
            "decision_evaluation_id",
            "candidate_id",
            name="uq_decision_candidate",
        ),
        UniqueConstraint(
            "decision_evaluation_id",
            "result_role",
            "result_position",
            name="uq_decision_candidate_result_position",
        ),
        CheckConstraint(
            "result_role IN ('selected', 'alternative', 'rejected')",
            name="ck_decision_candidate_result_role",
        ),
        CheckConstraint(
            "("
            "(result_role = 'selected' AND result_position IS NULL) OR "
            "(result_role IN ('alternative', 'rejected') "
            "AND result_position IS NOT NULL AND result_position >= 0)"
            ")",
            name="ck_decision_candidate_result_position",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_evaluation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("decision_evaluations.id"),
        nullable=False,
        index=True,
    )
    candidate_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_category: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    expected_gain: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    transition_cost: Mapped[float] = mapped_column(Float, nullable=False)
    reversible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    result_role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment=(
            "Persistence-only DecisionResult membership: selected, alternative, "
            "or rejected. Never inferred from policy, ranking, prediction, or score."
        ),
    )
    result_position: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment=(
            "Zero-based position within DecisionResult alternatives or "
            "rejected_alternatives; NULL for the selected candidate."
        ),
    )

    decision_evaluation: Mapped["DecisionEvaluationDB"] = relationship(
        back_populates="candidates",
        foreign_keys=[decision_evaluation_id],
    )
    policy_result: Mapped["DecisionPolicyResultDB | None"] = relationship(
        back_populates="candidate",
        uselist=False,
    )
    prediction: Mapped["DecisionPredictionDB | None"] = relationship(
        back_populates="candidate",
        uselist=False,
    )
    score: Mapped["DecisionScoreDB | None"] = relationship(
        back_populates="candidate",
        uselist=False,
    )
    ranking: Mapped["DecisionRankingDB | None"] = relationship(
        back_populates="candidate",
        foreign_keys="DecisionRankingDB.candidate_id",
        uselist=False,
    )


class DecisionPolicyResultDB(Base):
    __tablename__ = "decision_policy_results"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_decision_policy_candidate"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("decision_candidates.id"),
        nullable=False,
        index=True,
    )
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    violations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    candidate: Mapped["DecisionCandidateDB"] = relationship(
        back_populates="policy_result",
        foreign_keys=[candidate_id],
    )


class DecisionPredictionDB(Base):
    __tablename__ = "decision_predictions"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_decision_prediction_candidate"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("decision_candidates.id"),
        nullable=False,
        index=True,
    )
    expected_reward_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_hashrate_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_power_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    uncertainty: Mapped[float] = mapped_column(Float, nullable=False)
    horizon: Mapped[str] = mapped_column(String(64), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    candidate: Mapped["DecisionCandidateDB"] = relationship(
        back_populates="prediction",
        foreign_keys=[candidate_id],
    )


class DecisionScoreDB(Base):
    __tablename__ = "decision_scores"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_decision_score_candidate"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("decision_candidates.id"),
        nullable=False,
        index=True,
    )
    benefit: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    risk: Mapped[float] = mapped_column(Float, nullable=False)
    action_cost: Mapped[float] = mapped_column(Float, nullable=False)
    uncertainty: Mapped[float] = mapped_column(Float, nullable=False)
    utility_score: Mapped[float] = mapped_column(Float, nullable=False)

    candidate: Mapped["DecisionCandidateDB"] = relationship(
        back_populates="score",
        foreign_keys=[candidate_id],
    )


class DecisionRankingDB(Base):
    __tablename__ = "decision_rankings"
    __table_args__ = (
        UniqueConstraint(
            "decision_evaluation_id",
            "rank_position",
            name="uq_decision_ranking_decision_rank",
        ),
        UniqueConstraint(
            "decision_evaluation_id",
            "candidate_id",
            name="uq_decision_ranking_candidate",
        ),
        UniqueConstraint("candidate_id", name="uq_decision_ranking_candidate_row"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_evaluation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("decision_evaluations.id"),
        nullable=False,
        index=True,
    )
    candidate_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("decision_candidates.id"),
        nullable=False,
        index=True,
    )
    rank_position: Mapped[int] = mapped_column(Integer, nullable=False)

    decision_evaluation: Mapped["DecisionEvaluationDB"] = relationship(
        back_populates="rankings",
        foreign_keys=[decision_evaluation_id],
    )
    candidate: Mapped["DecisionCandidateDB"] = relationship(
        back_populates="ranking",
        foreign_keys=[candidate_id],
    )


class DecisionConfidenceDB(Base):
    """Persist the authoritative Phase 9 DecisionConfidenceResult artifact."""

    __tablename__ = "decision_confidence"
    __table_args__ = (
        UniqueConstraint(
            "decision_evaluation_id",
            name="uq_decision_confidence_evaluation",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_evaluation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("decision_evaluations.id"),
        nullable=False,
        index=True,
    )
    candidate_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("decision_candidates.id"),
        nullable=False,
        index=True,
        comment=(
            "Persisted candidate-row identity for "
            "DecisionConfidenceResult.candidate_id."
        ),
    )
    evidence_inputs_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment=(
            "Ordered JSON representation of DecisionConfidenceResult.evidence_inputs."
        ),
    )
    context_freshness: Mapped[str] = mapped_column(String(32), nullable=False)
    miner_freshness: Mapped[str] = mapped_column(String(32), nullable=False)
    hardware_freshness: Mapped[str] = mapped_column(String(32), nullable=False)
    prediction_reliability: Mapped[float] = mapped_column(Float, nullable=False)
    overall_confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Authoritative persisted Phase 9 aggregate confidence; NULL remains NULL.",
    )
    limitations_json: Mapped[str] = mapped_column(Text, nullable=False)

    decision_evaluation: Mapped["DecisionEvaluationDB"] = relationship(
        back_populates="confidence_artifact",
        foreign_keys=[decision_evaluation_id],
    )
    candidate: Mapped["DecisionCandidateDB"] = relationship(
        foreign_keys=[candidate_id],
    )


class DecisionExplanationDB(Base):
    """Persist the authoritative structured Phase 11 explanation artifact."""

    __tablename__ = "decision_explanations"
    __table_args__ = (
        UniqueConstraint("decision_evaluation_id", name="uq_decision_explanation_evaluation"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_evaluation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("decision_evaluations.id"),
        nullable=False,
        index=True,
    )
    explanation_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Authoritative persisted structured Phase 11 DecisionExplanation.",
    )

    decision_evaluation: Mapped["DecisionEvaluationDB"] = relationship(
        back_populates="explanation",
        foreign_keys=[decision_evaluation_id],
    )
