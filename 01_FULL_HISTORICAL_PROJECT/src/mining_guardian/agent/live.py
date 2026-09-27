"""One-shot read-only live WorldState construction for M2.1.1."""

from typing import Protocol

from ..core.algorithm_registry import AlgorithmRegistry
from ..models import HardwareSample, MinerSnapshot
from ..storage.repository import SessionRepository
from .context import (
    WorldStateBuilder,
    _context_validity,
    guardian_session_status,
    session_metrics,
)
from .models import (
    MeasuredWorldFacts,
    MiningWorldState,
    WorldGPUState,
    WorldWorkloadState,
)
from .temporal import (
    FreshnessPolicy,
    MinerReachability,
    ObservationOrigin,
    age_seconds,
    ensure_utc,
    utc_now,
)


class ReadOnlyMinerClient(Protocol):
    """Minimal read-only miner interface required for a live probe."""

    async def snapshot(self) -> MinerSnapshot | None: ...


class ReadOnlyNVMLClient(Protocol):
    """Minimal read-only hardware interface required for a live probe."""

    def read_telemetry(self, gpu_index: int = 0) -> HardwareSample | None: ...


class LiveWorldStateBuilder:
    """Build one ephemeral current observation without persisting telemetry or sessions."""

    def __init__(
        self,
        miner_client: ReadOnlyMinerClient,
        hardware_client: ReadOnlyNVMLClient,
        algorithm_registry: AlgorithmRegistry,
        session_repository: SessionRepository,
        *,
        gpu_index: int = 0,
        freshness_policy: FreshnessPolicy | None = None,
    ) -> None:
        self.miner_client = miner_client
        self.hardware_client = hardware_client
        self.algorithm_registry = algorithm_registry
        self.session_repository = session_repository
        self.gpu_index = gpu_index
        self.freshness_policy = freshness_policy or FreshnessPolicy()

    async def build(self) -> MiningWorldState:
        """Probe miner and GPU exactly once each and return an ephemeral state."""

        latest_session = self.session_repository.get_latest()

        miner_snapshot = await self.miner_client.snapshot()
        miner_observed_at = utc_now() if miner_snapshot is not None else None

        hardware_sample = self.hardware_client.read_telemetry(self.gpu_index)
        hardware_observed_at = utc_now() if hardware_sample is not None else None

        generated_at = utc_now()
        workloads = self._workloads(miner_snapshot)
        gpus = self._gpus(hardware_sample, miner_snapshot)

        miner_freshness = self.freshness_policy.classify_timestamp(
            miner_observed_at,
            now=generated_at,
        )
        hardware_freshness = self.freshness_policy.classify_timestamp(
            hardware_observed_at,
            now=generated_at,
        )
        overall_freshness = self.freshness_policy.conservative_overall(
            miner_freshness,
            hardware_freshness,
        )
        observed = [
            value for value in (miner_observed_at, hardware_observed_at) if value is not None
        ]
        observation_timestamp = max(observed) if observed else generated_at

        miner_name = (
            miner_snapshot.miner
            if miner_snapshot is not None
            else latest_session.miner if latest_session is not None else "srbminer"
        )
        facts = MeasuredWorldFacts(
            session_id=latest_session.session_id if latest_session is not None else None,
            session_start_time=(
                ensure_utc(latest_session.start_time) if latest_session is not None else None
            ),
            session_end_time=(
                ensure_utc(latest_session.end_time) if latest_session is not None else None
            ),
            guardian_session_status=guardian_session_status(latest_session),
            session_state=latest_session.state if latest_session is not None else None,
            session_health=latest_session.health if latest_session is not None else None,
            miner=miner_name,
            miner_version=miner_snapshot.miner_version if miner_snapshot is not None else None,
            miner_reachability=(
                MinerReachability.REACHABLE
                if miner_snapshot is not None
                else MinerReachability.UNREACHABLE
            ),
            payout_coin=latest_session.payout_coin if latest_session is not None else None,
            workloads=workloads,
            gpus=gpus,
        )
        missing = WorldStateBuilder._missing_signals(facts)
        warnings: list[str] = []
        if miner_snapshot is None:
            warnings.append("SRBMiner API was unreachable or returned an invalid snapshot.")
        if hardware_sample is None:
            warnings.append("NVML telemetry was unavailable for the live probe.")
        if latest_session is not None and latest_session.end_time is not None:
            warnings.append(
                "Latest Guardian session is ended; live reachability does not make it active."
            )

        return MiningWorldState(
            timestamp=generated_at,
            observation_timestamp=observation_timestamp,
            observation_origin=ObservationOrigin.LIVE_PROBE,
            observation_age_seconds=age_seconds(observation_timestamp, generated_at),
            freshness=overall_freshness,
            latest_miner_sample_at=miner_observed_at,
            latest_hardware_sample_at=hardware_observed_at,
            miner_sample_age_seconds=age_seconds(miner_observed_at, generated_at),
            hardware_sample_age_seconds=age_seconds(hardware_observed_at, generated_at),
            miner_freshness=miner_freshness,
            hardware_freshness=hardware_freshness,
            facts=facts,
            derived=session_metrics(latest_session, now=generated_at),
            missing_signals=missing,
            context_validity=_context_validity(
                freshness=overall_freshness,
                missing_signals=missing,
                extra_warnings=warnings,
            ),
        )

    def _workloads(self, snapshot: MinerSnapshot | None) -> list[WorldWorkloadState]:
        if snapshot is None:
            return []

        result: list[WorldWorkloadState] = []
        for workload in snapshot.workloads:
            record, _ = self.algorithm_registry.resolve(
                workload.raw_algorithm_name,
                scope_type="miner",
                scope_name=snapshot.miner,
                discover=False,
            )
            if record is not None:
                workload.canonical_algorithm_id = record.algorithm_id
                workload.canonical_algorithm_name = record.canonical_name
            result.append(
                WorldWorkloadState(
                    raw_algorithm_name=workload.raw_algorithm_name,
                    canonical_algorithm_id=record.algorithm_id if record is not None else None,
                    canonical_algorithm_name=record.canonical_name if record is not None else None,
                    local_hashrate_hs=workload.hashrate_hs,
                    accepted_shares=workload.accepted_shares,
                    rejected_shares=workload.rejected_shares,
                    invalid_shares=workload.invalid_shares,
                    miner_uptime_seconds=snapshot.uptime_seconds,
                    gpu_errors=snapshot.gpu_errors,
                    device_ids=workload.device_ids,
                )
            )
        return result

    @staticmethod
    def _gpus(
        sample: HardwareSample | None,
        snapshot: MinerSnapshot | None,
    ) -> list[WorldGPUState]:
        if sample is None:
            return []
        algorithm_ids: list[str] = []
        if snapshot is not None:
            algorithm_ids = [
                workload.canonical_algorithm_id
                for workload in snapshot.workloads
                if workload.canonical_algorithm_id is not None
            ]
        return [
            WorldGPUState(
                gpu_id=sample.gpu_id,
                miner=snapshot.miner if snapshot is not None else sample.miner,
                algorithm_ids=algorithm_ids or sample.algorithm_ids,
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
        ]
