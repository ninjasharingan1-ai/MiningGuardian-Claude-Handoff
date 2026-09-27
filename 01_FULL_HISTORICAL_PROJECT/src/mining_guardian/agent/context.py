"""Deterministic world-state and context-window builders for M2.1/M2.1.1."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import fmean
from typing import Protocol

from ..models import HardwareSample, MinerSample, SessionRecord
from ..storage.agent_repository import AgentDecisionRepository, AgentLessonRepository
from ..storage.repository import HardwareSampleRepository, MinerSampleRepository, SessionRepository
from .models import (
    AgentDecision,
    AgentHypothesis,
    AgentLesson,
    AgentWorkingMemory,
    ContextValidity,
    DerivedWorldMetrics,
    GPUWindowSummary,
    MeasuredWorldFacts,
    MiningWorldState,
    TelemetryWindowSummary,
    WorkloadWindowSummary,
    WorldGPUState,
    WorldWorkloadState,
)
from .temporal import (
    FreshnessLevel,
    FreshnessPolicy,
    GuardianSessionStatus,
    MinerReachability,
    ObservationOrigin,
    age_seconds,
    ensure_utc,
    utc_now,
)


class NoTelemetrySessionError(RuntimeError):
    """Raised when agent context is requested before any persisted session exists."""


class _TimestampedSample(Protocol):
    """Read-only timestamp contract shared by persisted telemetry sample models."""

    @property
    def timestamp(self) -> datetime: ...


def _utc_timestamps(samples: Iterable[_TimestampedSample]) -> set[datetime]:
    timestamps: set[datetime] = set()
    for sample in samples:
        timestamp = ensure_utc(sample.timestamp)
        if timestamp is not None:
            timestamps.add(timestamp)
    return timestamps


@dataclass(frozen=True)
class ContextWindowSpec:
    label: str
    duration: timedelta | None


DEFAULT_WINDOWS = (
    ContextWindowSpec("5m", timedelta(minutes=5)),
    ContextWindowSpec("30m", timedelta(minutes=30)),
    ContextWindowSpec("6h", timedelta(hours=6)),
    ContextWindowSpec("current_session", None),
)


def _mean(values: list[float]) -> float | None:
    return fmean(values) if values else None


def _delta(values: list[int]) -> int | None:
    return values[-1] - values[0] if len(values) >= 2 else None


def _slope(samples: list[tuple[datetime, float]]) -> float | None:
    if len(samples) < 2:
        return None
    first_time, first_value = samples[0]
    last_time, last_value = samples[-1]
    elapsed = (last_time - first_time).total_seconds()
    if elapsed <= 0:
        return None
    return (last_value - first_value) / elapsed


def guardian_session_status(session: SessionRecord | None) -> GuardianSessionStatus:
    """Derive Guardian lifecycle only from persisted Guardian session facts."""

    if session is None:
        return GuardianSessionStatus.UNKNOWN
    if session.end_time is not None:
        return GuardianSessionStatus.ENDED
    return GuardianSessionStatus.ACTIVE


def session_metrics(
    session: SessionRecord | None,
    *,
    now: datetime,
) -> DerivedWorldMetrics:
    """Return active age or completed duration without conflating the two."""

    if session is None:
        return DerivedWorldMetrics()
    start = ensure_utc(session.start_time)
    end = ensure_utc(session.end_time)
    now_utc = ensure_utc(now)
    if start is None or now_utc is None:
        return DerivedWorldMetrics()
    if end is None:
        return DerivedWorldMetrics(
            session_age_seconds=max(0.0, (now_utc - start).total_seconds()),
            session_duration_seconds=None,
        )
    return DerivedWorldMetrics(
        session_age_seconds=None,
        session_duration_seconds=max(0.0, (end - start).total_seconds()),
    )


def _context_validity(
    *,
    freshness: FreshnessLevel,
    missing_signals: list[str],
    extra_warnings: list[str] | None = None,
) -> ContextValidity:
    warnings = list(extra_warnings or [])
    if freshness is FreshnessLevel.STALE:
        warnings.append("Current-state telemetry is stale; treat it as historical evidence.")
    elif freshness is FreshnessLevel.UNKNOWN:
        warnings.append("Current-state freshness is unknown or a required source is unavailable.")
    return ContextValidity(
        is_current_state_usable=freshness in {FreshnessLevel.FRESH, FreshnessLevel.RECENT},
        freshness=freshness,
        missing_required_signals=list(missing_signals),
        warnings=list(dict.fromkeys(warnings)),
    )


class WorldStateBuilder:
    """Build a temporally explicit world state from persisted M0/M1 telemetry."""

    def __init__(
        self,
        session_repository: SessionRepository,
        miner_repository: MinerSampleRepository,
        hardware_repository: HardwareSampleRepository,
        *,
        freshness_policy: FreshnessPolicy | None = None,
    ) -> None:
        self.session_repository = session_repository
        self.miner_repository = miner_repository
        self.hardware_repository = hardware_repository
        self.freshness_policy = freshness_policy or FreshnessPolicy()

    def build(
        self,
        session_id: str | None = None,
        *,
        now: datetime | None = None,
    ) -> MiningWorldState:
        generated_at = ensure_utc(now) or utc_now()
        session = (
            self.session_repository.get_by_id(session_id)
            if session_id is not None
            else self.session_repository.get_latest()
        )
        if session is None:
            raise NoTelemetrySessionError("No persisted mining session is available.")

        miner_samples = self.miner_repository.get_all_by_session(session.session_id)
        hardware_samples = self.hardware_repository.get_all_by_session(session.session_id)
        latest_workloads = self._latest_workloads(miner_samples)
        latest_gpus = self._latest_gpus(hardware_samples)
        miner_version = self._latest_miner_version(miner_samples)

        latest_miner_at = self._latest_timestamp(miner_samples)
        latest_hardware_at = self._latest_timestamp(hardware_samples)
        miner_age = age_seconds(latest_miner_at, generated_at)
        hardware_age = age_seconds(latest_hardware_at, generated_at)
        miner_freshness = self.freshness_policy.classify_age(miner_age)
        hardware_freshness = self.freshness_policy.classify_age(hardware_age)
        overall_freshness = self.freshness_policy.conservative_overall(
            miner_freshness,
            hardware_freshness,
        )
        known_timestamps = [
            value for value in (latest_miner_at, latest_hardware_at) if value is not None
        ]
        observation_timestamp = max(known_timestamps) if known_timestamps else None

        status = guardian_session_status(session)
        facts = MeasuredWorldFacts(
            session_id=session.session_id,
            session_start_time=ensure_utc(session.start_time),
            session_end_time=ensure_utc(session.end_time),
            guardian_session_status=status,
            session_state=session.state,
            session_health=session.health,
            miner=session.miner,
            miner_version=miner_version,
            miner_reachability=MinerReachability.UNKNOWN,
            payout_coin=session.payout_coin,
            workloads=latest_workloads,
            gpus=latest_gpus,
        )
        missing = self._missing_signals(facts)
        warnings = []
        if status is GuardianSessionStatus.ENDED:
            warnings.append("Latest Guardian session is ended; telemetry is historical.")
        return MiningWorldState(
            timestamp=generated_at,
            observation_timestamp=observation_timestamp,
            observation_origin=ObservationOrigin.PERSISTED,
            observation_age_seconds=age_seconds(observation_timestamp, generated_at),
            freshness=overall_freshness,
            latest_miner_sample_at=latest_miner_at,
            latest_hardware_sample_at=latest_hardware_at,
            miner_sample_age_seconds=miner_age,
            hardware_sample_age_seconds=hardware_age,
            miner_freshness=miner_freshness,
            hardware_freshness=hardware_freshness,
            facts=facts,
            derived=session_metrics(session, now=generated_at),
            missing_signals=missing,
            context_validity=_context_validity(
                freshness=overall_freshness,
                missing_signals=missing,
                extra_warnings=warnings,
            ),
        )

    @staticmethod
    def _latest_timestamp(samples: list[MinerSample] | list[HardwareSample]) -> datetime | None:
        timestamps = [
            timestamp
            for sample in samples
            if (timestamp := ensure_utc(sample.timestamp)) is not None
        ]
        return max(timestamps) if timestamps else None

    @staticmethod
    def _latest_workloads(samples: list[MinerSample]) -> list[WorldWorkloadState]:
        latest: dict[tuple[str, tuple[int, ...]], MinerSample] = {}
        for sample in samples:
            key = (sample.canonical_algorithm_id, tuple(sorted(sample.device_ids)))
            previous = latest.get(key)
            sample_time = ensure_utc(sample.timestamp)
            previous_time = ensure_utc(previous.timestamp) if previous is not None else None
            if previous is None or (
                sample_time is not None
                and previous_time is not None
                and sample_time >= previous_time
            ):
                latest[key] = sample
        return [
            WorldWorkloadState(
                raw_algorithm_name=sample.raw_algorithm_name,
                canonical_algorithm_id=sample.canonical_algorithm_id,
                canonical_algorithm_name=sample.canonical_algorithm_name,
                local_hashrate_hs=sample.local_hashrate_hs,
                accepted_shares=sample.accepted_shares,
                rejected_shares=sample.rejected_shares,
                invalid_shares=sample.invalid_shares,
                miner_uptime_seconds=sample.miner_uptime_seconds,
                gpu_errors=sample.gpu_errors,
                device_ids=sample.device_ids,
            )
            for _, sample in sorted(latest.items())
        ]

    @staticmethod
    def _latest_gpus(samples: list[HardwareSample]) -> list[WorldGPUState]:
        latest: dict[int, HardwareSample] = {}
        for sample in samples:
            previous = latest.get(sample.gpu_id)
            sample_time = ensure_utc(sample.timestamp)
            previous_time = ensure_utc(previous.timestamp) if previous is not None else None
            if previous is None or (
                sample_time is not None
                and previous_time is not None
                and sample_time >= previous_time
            ):
                latest[sample.gpu_id] = sample
        return [
            WorldGPUState(
                gpu_id=sample.gpu_id,
                miner=sample.miner,
                algorithm_ids=sample.algorithm_ids,
                temperature_c=sample.temperature_c,
                utilization_gpu=sample.utilization_gpu,
                utilization_memory=sample.utilization_memory,
                core_clock_mhz=sample.core_clock_mhz,
                memory_clock_mhz=sample.memory_clock_mhz,
                power_w=sample.power_w,
                power_limit_w=sample.power_limit_w,
                performance_state=sample.performance_state,
                throttle_reasons=sample.throttle_reasons,
                capability_states=sample.capability_states,
            )
            for _, sample in sorted(latest.items())
        ]

    @staticmethod
    def _latest_miner_version(samples: list[MinerSample]) -> str | None:
        for sample in reversed(samples):
            value = sample.raw_data.get("miner_version")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _missing_signals(facts: MeasuredWorldFacts) -> list[str]:
        missing: list[str] = []
        if facts.miner_version is None:
            missing.append("miner_version")
        if not facts.workloads:
            missing.append("workloads")
        for workload in facts.workloads:
            identity = workload.canonical_algorithm_id or workload.raw_algorithm_name
            prefix = f"workloads.{identity}"
            if workload.canonical_algorithm_id is None:
                missing.append(f"{prefix}.canonical_algorithm_id")
            if workload.local_hashrate_hs is None:
                missing.append(f"{prefix}.hashrate_hs")
            if workload.accepted_shares is None:
                missing.append(f"{prefix}.accepted_shares")
            if workload.rejected_shares is None:
                missing.append(f"{prefix}.rejected_shares")
        if not facts.gpus:
            missing.append("gpu_telemetry")
        for gpu in facts.gpus:
            prefix = f"gpus.{gpu.gpu_id}"
            if gpu.temperature_c is None:
                missing.append(f"{prefix}.temperature_c")
            if gpu.power_w is None:
                missing.append(f"{prefix}.power_w")
            if gpu.utilization_gpu is None:
                missing.append(f"{prefix}.utilization_gpu")
        return missing


class ContextBuilder:
    """Summarize persisted telemetry with explicit historical/freshness semantics."""

    def __init__(
        self,
        session_repository: SessionRepository,
        miner_repository: MinerSampleRepository,
        hardware_repository: HardwareSampleRepository,
        *,
        windows: tuple[ContextWindowSpec, ...] = DEFAULT_WINDOWS,
        freshness_policy: FreshnessPolicy | None = None,
    ) -> None:
        self.session_repository = session_repository
        self.miner_repository = miner_repository
        self.hardware_repository = hardware_repository
        self.windows = windows
        self.freshness_policy = freshness_policy or FreshnessPolicy()

    def build(
        self,
        session_id: str,
        *,
        now: datetime | None = None,
    ) -> list[TelemetryWindowSummary]:
        session = self.session_repository.get_by_id(session_id)
        if session is None:
            raise NoTelemetrySessionError(f"Session {session_id!r} does not exist.")

        generated_at = ensure_utc(now) or utc_now()
        miner_samples = self.miner_repository.get_all_by_session(session_id)
        hardware_samples = self.hardware_repository.get_all_by_session(session_id)
        session_start = ensure_utc(session.start_time)
        session_end = ensure_utc(session.end_time)
        if session_start is None:
            return []

        status = guardian_session_status(session)
        effective_end = session_end or generated_at
        if effective_end > generated_at:
            effective_end = generated_at

        summaries: list[TelemetryWindowSummary] = []
        for spec in self.windows:
            start_time = session_start
            if spec.duration is not None:
                start_time = max(session_start, effective_end - spec.duration)

            window_miners = [
                sample
                for sample in miner_samples
                if self._in_window(sample.timestamp, start_time, effective_end)
            ]
            window_hardware = [
                sample
                for sample in hardware_samples
                if self._in_window(sample.timestamp, start_time, effective_end)
            ]
            timestamps = _utc_timestamps(window_miners)
            timestamps.update(_utc_timestamps(window_hardware))
            if len(timestamps) < 2:
                continue

            latest_sample_at = max(timestamps)
            label = spec.label
            if spec.duration is None and status is GuardianSessionStatus.ENDED:
                label = "last_session"

            summaries.append(
                TelemetryWindowSummary(
                    label=label,
                    start_time=start_time,
                    end_time=effective_end,
                    latest_sample_at=latest_sample_at,
                    observation_origin=ObservationOrigin.PERSISTED,
                    freshness=self.freshness_policy.classify_timestamp(
                        latest_sample_at,
                        now=generated_at,
                    ),
                    session_status=status,
                    duration_seconds=max(0.0, (effective_end - start_time).total_seconds()),
                    miner_sample_count=len(window_miners),
                    hardware_sample_count=len(window_hardware),
                    workloads=self._summarize_workloads(window_miners),
                    gpus=self._summarize_gpus(window_hardware),
                )
            )
        return summaries

    @staticmethod
    def _in_window(timestamp: datetime, start: datetime, end: datetime) -> bool:
        value = ensure_utc(timestamp)
        return value is not None and start <= value <= end

    @staticmethod
    def _summarize_workloads(samples: list[MinerSample]) -> list[WorkloadWindowSummary]:
        grouped: dict[tuple[str, tuple[int, ...]], list[MinerSample]] = defaultdict(list)
        for sample in samples:
            key = (sample.canonical_algorithm_id, tuple(sorted(sample.device_ids)))
            grouped[key].append(sample)

        summaries: list[WorkloadWindowSummary] = []
        for (algorithm_id, device_ids), group in sorted(grouped.items()):
            group.sort(key=lambda sample: sample.timestamp)
            hashrates: list[float] = []
            hashrate_points: list[tuple[datetime, float]] = []
            accepted: list[int] = []
            rejected: list[int] = []
            errors: list[int] = []
            for sample in group:
                sample_time = ensure_utc(sample.timestamp)
                if sample.local_hashrate_hs is not None:
                    hashrates.append(sample.local_hashrate_hs)
                    if sample_time is not None:
                        hashrate_points.append((sample_time, sample.local_hashrate_hs))
                if sample.accepted_shares is not None:
                    accepted.append(sample.accepted_shares)
                if sample.rejected_shares is not None:
                    rejected.append(sample.rejected_shares)
                if sample.gpu_errors is not None:
                    errors.append(sample.gpu_errors)
            raw_names = list(dict.fromkeys(sample.raw_algorithm_name for sample in group))
            summaries.append(
                WorkloadWindowSummary(
                    algorithm_id=algorithm_id,
                    canonical_algorithm_name=group[-1].canonical_algorithm_name,
                    raw_algorithm_names=raw_names,
                    device_ids=list(device_ids),
                    sample_count=len(group),
                    mean_hashrate_hs=_mean(hashrates),
                    min_hashrate_hs=min(hashrates) if hashrates else None,
                    max_hashrate_hs=max(hashrates) if hashrates else None,
                    hashrate_slope_hs_per_second=_slope(hashrate_points),
                    accepted_share_delta=_delta(accepted),
                    rejected_share_delta=_delta(rejected),
                    error_delta=_delta(errors),
                    missing_hashrate_fraction=(
                        (len(group) - len(hashrates)) / len(group) if group else 1.0
                    ),
                )
            )
        return summaries

    @staticmethod
    def _summarize_gpus(samples: list[HardwareSample]) -> list[GPUWindowSummary]:
        grouped: dict[int, list[HardwareSample]] = defaultdict(list)
        for sample in samples:
            grouped[sample.gpu_id].append(sample)

        summaries: list[GPUWindowSummary] = []
        for gpu_id, group in sorted(grouped.items()):
            temperatures: list[float] = []
            powers: list[float] = []
            utilizations: list[float] = []
            for sample in group:
                if sample.temperature_c is not None:
                    temperatures.append(sample.temperature_c)
                if sample.power_w is not None:
                    powers.append(sample.power_w)
                if sample.utilization_gpu is not None:
                    utilizations.append(sample.utilization_gpu)
            measured_count = len(temperatures) + len(powers) + len(utilizations)
            expected_count = len(group) * 3
            missing_fraction = (
                (expected_count - measured_count) / expected_count if expected_count else 1.0
            )
            summaries.append(
                GPUWindowSummary(
                    gpu_id=gpu_id,
                    sample_count=len(group),
                    mean_temperature_c=_mean(temperatures),
                    max_temperature_c=max(temperatures) if temperatures else None,
                    mean_power_w=_mean(powers),
                    mean_utilization_gpu=_mean(utilizations),
                    missing_data_fraction=missing_fraction,
                )
            )
        return summaries


class WorkingMemoryBuilder:
    """Assemble bounded structured context supplied to a future reasoning model."""

    def __init__(
        self,
        world_state_builder: WorldStateBuilder,
        context_builder: ContextBuilder,
        decision_repository: AgentDecisionRepository,
        lesson_repository: AgentLessonRepository,
    ) -> None:
        self.world_state_builder = world_state_builder
        self.context_builder = context_builder
        self.decision_repository = decision_repository
        self.lesson_repository = lesson_repository

    def build(
        self,
        session_id: str | None = None,
        *,
        now: datetime | None = None,
    ) -> AgentWorkingMemory:
        world_state = self.world_state_builder.build(session_id, now=now)
        resolved_session_id = world_state.facts.session_id
        if resolved_session_id is None:
            raise NoTelemetrySessionError("No persisted mining session is available.")

        context_windows = self.context_builder.build(
            resolved_session_id,
            now=world_state.timestamp,
        )
        recent_decisions: list[AgentDecision] = self.decision_repository.get_recent(
            session_id=resolved_session_id,
            limit=5,
        )
        active_hypotheses = self._active_hypotheses(recent_decisions)
        active_algorithm_ids = {
            workload.canonical_algorithm_id
            for workload in world_state.facts.workloads
            if workload.canonical_algorithm_id is not None
        }
        lessons: list[AgentLesson] = self.lesson_repository.get_relevant(
            session_id=resolved_session_id,
            algorithm_ids=active_algorithm_ids,
            limit=5,
        )
        unresolved_questions = [
            f"Resolve missing signal: {signal}" for signal in world_state.missing_signals
        ]
        if not world_state.context_validity.is_current_state_usable:
            unresolved_questions.append(
                f"Refresh current telemetry before treating it as present truth "
                f"(freshness={world_state.freshness.value})."
            )
        return AgentWorkingMemory(
            world_state=world_state,
            context_windows=context_windows,
            active_hypotheses=active_hypotheses,
            recent_decisions=[decision.summary() for decision in recent_decisions],
            unresolved_questions=unresolved_questions,
            relevant_lessons=lessons,
        )

    @staticmethod
    def _active_hypotheses(decisions: list[AgentDecision]) -> list[AgentHypothesis]:
        result: list[AgentHypothesis] = []
        seen: set[str] = set()
        for decision in decisions:
            for hypothesis in decision.hypotheses:
                if hypothesis.status.value != "active" or hypothesis.hypothesis_id in seen:
                    continue
                seen.add(hypothesis.hypothesis_id)
                result.append(hypothesis)
        return result
