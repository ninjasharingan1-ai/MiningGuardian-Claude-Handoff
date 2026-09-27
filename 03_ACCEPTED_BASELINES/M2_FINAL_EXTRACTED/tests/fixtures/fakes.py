from datetime import datetime

from mining_guardian.enums import CapabilityState
from mining_guardian.models import (
    GPUCapabilities,
    GPUInfo,
    HardwareSample,
    MinerHealth,
    MinerSnapshot,
    MinerStats,
    MinerWorkload,
)


class FakeSRBMinerClient:
    def __init__(
        self,
        alive: bool = True,
        algorithm: str = "pearlhash",
        hashrate_hs: float | None = 27_400_000.0,
        workloads: list[MinerWorkload] | None = None,
        malformed: bool = False,
    ):
        self.alive = alive
        self.malformed = malformed
        self._workloads = workloads or [
            MinerWorkload(
                raw_algorithm_name=algorithm,
                hashrate_hs=hashrate_hs,
                accepted_shares=100,
                rejected_shares=5,
                invalid_shares=1,
                device_ids=[0],
            )
        ]
        self.uptime_seconds = 3600.0
        self.gpu_errors = 0

    async def snapshot(self) -> MinerSnapshot | None:
        if not self.alive or self.malformed:
            return None
        return MinerSnapshot(
            miner="srbminer",
            uptime_seconds=self.uptime_seconds,
            workloads=[workload.model_copy(deep=True) for workload in self._workloads],
            gpu_errors=self.gpu_errors,
        )

    async def health(self) -> MinerHealth:
        if not self.alive:
            return MinerHealth(is_alive=False, error_message="Miner is offline")
        return MinerHealth(is_alive=True, uptime_seconds=self.uptime_seconds)

    async def stats(self) -> MinerStats | None:
        snapshot = await self.snapshot()
        if snapshot is None or not snapshot.workloads:
            return None
        workload = snapshot.workloads[0]
        return MinerStats(
            algorithm=workload.raw_algorithm_name,
            local_hashrate_hs=workload.hashrate_hs,
            accepted_shares=workload.accepted_shares,
            rejected_shares=workload.rejected_shares,
            invalid_shares=workload.invalid_shares,
            gpu_errors=self.gpu_errors,
        )

    async def local_hashrate_hs(self) -> float | None:
        stats = await self.stats()
        return stats.local_hashrate_hs if stats else None

    async def accepted_shares(self) -> int | None:
        stats = await self.stats()
        return stats.accepted_shares if stats else None

    async def rejected_shares(self) -> int | None:
        stats = await self.stats()
        return stats.rejected_shares if stats else None


class FakeNVMLClient:
    def __init__(
        self,
        available: bool = True,
        gpu_name: str = "NVIDIA RTX 4050 Laptop",
        temperature_c: float | None = 50.0,
        utilization_gpu: float | None = 75.0,
        power_w: float | None = 45.0,
    ):
        self.initialized = available
        self.gpu_name = gpu_name
        self.temperature_c = temperature_c
        self.utilization_gpu = utilization_gpu
        self.power_w = power_w

    def probe_capabilities(self, gpu_index: int = 0) -> GPUCapabilities:
        state = CapabilityState.SUPPORTED if self.initialized else CapabilityState.UNKNOWN
        return GPUCapabilities(
            can_read_temperature=state,
            can_read_clocks=state,
            can_read_power=state,
            can_read_utilization=state,
            can_read_throttle_reasons=state,
        )

    def get_gpu_info(self, gpu_index: int = 0) -> GPUInfo | None:
        if not self.initialized:
            return None
        return GPUInfo(gpu_index=gpu_index, name=self.gpu_name, capabilities=self.probe_capabilities(gpu_index))

    def read_telemetry(self, gpu_index: int = 0) -> HardwareSample | None:
        if not self.initialized:
            return None
        return HardwareSample(
            timestamp=datetime.now(),
            session_id="",
            gpu_id=gpu_index,
            temperature_c=self.temperature_c,
            utilization_gpu=self.utilization_gpu,
            utilization_memory=60.0,
            core_clock_mhz=2250.0,
            memory_clock_mhz=5001.0,
            power_w=self.power_w,
            power_limit_w=90.0,
            performance_state="P0",
            throttle_reasons=None,
        )

    def close(self) -> None:
        self.initialized = False
