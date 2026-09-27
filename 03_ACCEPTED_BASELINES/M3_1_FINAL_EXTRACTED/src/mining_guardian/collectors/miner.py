from datetime import datetime

from ..core import AlgorithmRegistry
from ..logging import get_logger
from ..models import MinerSample, MinerSnapshot

logger = get_logger(__name__)


class MinerCollector:
    def __init__(self, miner_client, registry: AlgorithmRegistry):
        self.miner_client = miner_client
        self.registry = registry
        self.last_discoveries: list[tuple[str, str]] = []

    async def collect(self, session_id: str) -> list[MinerSample]:
        self.last_discoveries = []
        snapshot = await self.miner_client.snapshot()
        if snapshot is None:
            logger.warning("miner_sample_collection_failed")
            return []

        return self.project_snapshot(snapshot, session_id)

    def project_snapshot(self, snapshot: MinerSnapshot, session_id: str) -> list[MinerSample]:
        """Explicit snapshot-to-legacy projection; performs no additional miner read."""
        self.last_discoveries = []

        samples: list[MinerSample] = []
        for workload in snapshot.workloads:
            record, created = self.registry.resolve(
                workload.raw_algorithm_name,
                scope_type="miner",
                scope_name=snapshot.miner,
                discover=True,
            )
            if record is None:
                continue
            if created:
                self.last_discoveries.append((workload.raw_algorithm_name, record.algorithm_id))
            workload.canonical_algorithm_id = record.algorithm_id
            workload.canonical_algorithm_name = record.canonical_name
            raw_data = dict(workload.raw_data)
            if snapshot.miner_version is not None:
                raw_data["miner_version"] = snapshot.miner_version
            samples.append(
                MinerSample(
                    timestamp=datetime.now(),
                    session_id=session_id,
                    miner=snapshot.miner,
                    raw_algorithm_name=workload.raw_algorithm_name,
                    canonical_algorithm_id=record.algorithm_id,
                    canonical_algorithm_name=record.canonical_name,
                    local_hashrate_hs=workload.hashrate_hs,
                    accepted_shares=workload.accepted_shares,
                    rejected_shares=workload.rejected_shares,
                    invalid_shares=workload.invalid_shares,
                    miner_uptime_seconds=snapshot.uptime_seconds,
                    gpu_errors=snapshot.gpu_errors,
                    device_ids=workload.device_ids,
                    raw_data=raw_data,
                )
            )
        return samples
