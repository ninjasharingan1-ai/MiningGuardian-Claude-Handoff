"""Independent source collection and explicit storage failures, without control."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from mining_guardian.logging import get_logger
from mining_guardian.models import MinerSnapshot

from .continuity import AcquisitionContext, ContinuityEvidence, ContinuityTracker
from .miner import MinerAcquisition
from .models import Quality, RuntimeObservation, Source, with_conditions
from .pool import pool_observations
from .temporal import Clock, FreshnessRule, elapsed, evaluate_freshness

logger = get_logger(__name__)


class MinerSource(Protocol):
    async def collect(self, correlation_id: UUID, guardian_session_id: str | None) -> MinerAcquisition: ...


class HardwareSource(Protocol):
    def collect(self, gpu_index: int, correlation_id: UUID,
                guardian_session_id: str | None) -> list[RuntimeObservation]: ...


class EvidenceSink(Protocol):
    def save_cycle(self, records: list[RuntimeObservation]) -> None: ...


@dataclass
class CycleResult:
    context: AcquisitionContext
    observations: list[RuntimeObservation]
    stored: bool
    snapshot: MinerSnapshot | None
    durations: dict[str, float]
    failure_count: int


class RuntimeObserver:
    def __init__(self, miner: MinerSource, hardware: HardwareSource, sink: EvidenceSink, *,
                 gpu_index: int = 0, clock: Clock | None = None,
                 freshness_rules: tuple[FreshnessRule, ...] = (),
                 prepare_miner: Callable[[MinerSnapshot], None] | None = None):
        self.miner, self.hardware, self.sink = miner, hardware, sink
        self.gpu_index = gpu_index
        self.clock = clock or Clock()
        self.freshness_rules = freshness_rules
        if len({(r.source, r.signal) for r in freshness_rules}) != len(freshness_rules):
            raise ValueError("ambiguous freshness configuration")
        self.prepare_miner = prepare_miner
        self.continuity = ContinuityTracker()
        self.instance = f"observer:{uuid4()}"
        self.failure_count = 0
        self.pending_failure: RuntimeObservation | None = None
        self.previous_durations: dict[str, float] | None = None

    def _diagnostic(self, context: AcquisitionContext, signal: str, *,
                    quality: Quality = Quality.VALID, value=None, error: Exception | None = None) -> RuntimeObservation:
        now = self.clock.now()
        return RuntimeObservation(source=Source.OBSERVER, source_instance=self.instance,
            signal=signal, value=value, observation_time=now, ingestion_time=now,
            unit="s" if signal.endswith("_seconds") else None,
            correlation_id=context.correlation_id, guardian_session_id=context.guardian_session_id,
            quality=quality, quality_metadata={"error_type": type(error).__name__ if error else None})

    @staticmethod
    def _checked(records: list[RuntimeObservation], source: Source,
                 context: AcquisitionContext) -> list[RuntimeObservation]:
        validated = [RuntimeObservation.model_validate(r.model_dump()) for r in records]
        if any(r.source != source or r.correlation_id != context.correlation_id
               or r.guardian_session_id != context.guardian_session_id for r in validated):
            raise ValueError("adapter_acquisition_identity_mismatch")
        return validated

    async def collect_cycle(self, guardian_session_id: str | None) -> CycleResult:
        context = AcquisitionContext(guardian_session_id)
        start = self.clock.monotonic()
        records: list[RuntimeObservation] = []
        snapshot = None
        request_seconds = 0.0
        try:
            acquisition = await self.miner.collect(context.correlation_id, guardian_session_id)
            records.extend(self._checked(acquisition.observations, Source.SRBMINER_HTTP, context))
            snapshot = acquisition.snapshot
            request_seconds = acquisition.request_seconds
        except Exception as exc:
            records.append(RuntimeObservation(source=Source.SRBMINER_HTTP, signal="availability",
                ingestion_time=self.clock.now(), correlation_id=context.correlation_id,
                guardian_session_id=guardian_session_id, quality=Quality.SOURCE_UNAVAILABLE,
                quality_metadata={"error_type": type(exc).__name__}))
        gpu_start = self.clock.monotonic()
        try:
            records.extend(self._checked(self.hardware.collect(self.gpu_index, context.correlation_id,
                                                              guardian_session_id), Source.NVML, context))
        except Exception as exc:
            records.append(RuntimeObservation(source=Source.NVML, signal="availability",
                ingestion_time=self.clock.now(), correlation_id=context.correlation_id,
                guardian_session_id=guardian_session_id, quality=Quality.SOURCE_UNAVAILABLE,
                quality_metadata={"error_type": type(exc).__name__}))
        gpu_seconds = elapsed(gpu_start, self.clock.monotonic)
        for record in tuple(records):
            if record.signal == "raw_payload" and record.source == Source.SRBMINER_HTTP:
                try:
                    records.extend(pool_observations(record))
                except Exception as exc:
                    records.append(self._diagnostic(context, "pool_promotion_failure", quality=Quality.CORRUPTED, error=exc))
        if snapshot is not None and self.prepare_miner is not None:
            try:
                self.prepare_miner(snapshot)
                identities = {w.raw_algorithm_name: w.canonical_algorithm_id for w in snapshot.workloads}
                records = [with_conditions(r, provenance={**r.provenance,
                    "canonical_algorithm_id": identities.get(str(r.provenance["raw_algorithm_name"]))})
                    if "raw_algorithm_name" in r.provenance else r for r in records]
            except Exception as exc:
                records.append(self._diagnostic(context, "algorithm_projection_failure",
                               quality=Quality.SOURCE_UNAVAILABLE, error=exc))
        classified = []
        for record in records:
            scope = ""
            if record.source == Source.SRBMINER_HTTP:
                if record.signal == "uptime_seconds":
                    scope = "miner_uptime"
                elif record.signal in ("total_shares", "accepted_shares", "rejected_shares", "invalid_shares"):
                    workload_id = record.provenance.get("miner_workload_id")
                    if isinstance(workload_id, (int, str)) and not isinstance(workload_id, bool):
                        scope = f"workload:{workload_id}:{record.provenance.get('raw_algorithm_name')}"
            if scope:
                record = self.continuity.assess(record, ContinuityEvidence(scope, cumulative=True))
            classified.append(evaluate_freshness(record, self.clock.now(), self.freshness_rules))
        records = classified
        if self.pending_failure is not None:
            records.append(self._diagnostic(context, "previous_storage_failure", quality=Quality.SOURCE_UNAVAILABLE,
                value={"failed_correlation_id": str(self.pending_failure.correlation_id),
                       "failure_observation_id": str(self.pending_failure.observation_id),
                       "failure_time": self.pending_failure.ingestion_time.isoformat(),
                       "unsaved_evidence": True}))
        if self.previous_durations is not None:
            records.append(self._diagnostic(context, "previous_cycle_durations_seconds", value=self.previous_durations))
        durations = {"miner_request_seconds": request_seconds, "gpu_request_seconds": gpu_seconds,
                     "poll_seconds": elapsed(start, self.clock.monotonic)}
        for signal, value in durations.items():
            records.append(self._diagnostic(context, signal, value=value))
        self.failure_count += sum(r.quality == Quality.SOURCE_UNAVAILABLE for r in records)
        persist_start = self.clock.monotonic()
        stored = False
        try:
            self.sink.save_cycle(records)
            stored = True
            self.pending_failure = None
        except Exception as exc:
            self.failure_count += 1
            failure = self._diagnostic(context, "storage_failure", quality=Quality.SOURCE_UNAVAILABLE, error=exc)
            records.append(failure)
            self.pending_failure = failure  # One bounded diagnostic, never an unbounded telemetry queue.
            logger.warning("runtime_storage_failure", guardian_session_id=guardian_session_id,
                correlation_id=str(context.correlation_id), observation_id=str(failure.observation_id),
                source=Source.OBSERVER.value, source_instance=self.instance, quality=failure.quality.value,
                error_type=type(exc).__name__)
        durations["persistence_seconds"] = elapsed(persist_start, self.clock.monotonic)
        durations["cycle_seconds"] = elapsed(start, self.clock.monotonic)
        self.previous_durations = dict(durations)
        logger.info("runtime_cycle", guardian_session_id=guardian_session_id,
            correlation_id=str(context.correlation_id), source=Source.OBSERVER.value,
            source_instance=self.instance, stored=stored, record_count=len(records),
            failure_count=self.failure_count, **durations)
        return CycleResult(context, records, stored, snapshot, durations, self.failure_count)
