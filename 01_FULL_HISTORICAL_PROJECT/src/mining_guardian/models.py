from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .enums import (
    AlgorithmStatus,
    CapabilityState,
    EventSeverity,
    EventType,
    SessionHealth,
    SessionState,
)


class GPUCapabilities(BaseModel):
    can_read_temperature: CapabilityState = CapabilityState.UNKNOWN
    can_read_clocks: CapabilityState = CapabilityState.UNKNOWN
    can_read_power: CapabilityState = CapabilityState.UNKNOWN
    can_read_utilization: CapabilityState = CapabilityState.UNKNOWN
    can_read_throttle_reasons: CapabilityState = CapabilityState.UNKNOWN


class GPUInfo(BaseModel):
    gpu_index: int
    name: str
    capabilities: GPUCapabilities = Field(default_factory=GPUCapabilities)


class AlgorithmRecord(BaseModel):
    algorithm_id: str
    canonical_name: str
    display_name: str
    status: AlgorithmStatus
    source: str
    last_verified_at: datetime | None = None
    underlying_asset: str | None = None
    optimizer_eligible: bool = False


class MinerDeviceIdentity(BaseModel):
    """Miner-local device identity; it must not be treated as an NVML index."""

    miner_device_id: int | None = None
    device_name: str | None = None
    bus_id: int | None = None
    topology_id: str | None = None
    vendor: str | None = None
    model: str | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)


class MinerWorkload(BaseModel):
    raw_algorithm_name: str
    canonical_algorithm_id: str | None = None
    canonical_algorithm_name: str | None = None
    hashrate_hs: float | None = None
    hashrate_windows_hs: dict[str, float] = Field(default_factory=dict)
    gpu_hashrate_total_hs: float | None = None
    gpu_hashrates_hs: dict[str, float] = Field(default_factory=dict)
    gpu_compute_errors: dict[str, int] = Field(default_factory=dict)
    gpu_efficiency_raw: dict[str, float] = Field(default_factory=dict)
    miner_device_names: list[str] = Field(default_factory=list)
    total_shares: int | None = None
    accepted_shares: int | None = None
    rejected_shares: int | None = None
    invalid_shares: int | None = None
    device_ids: list[int] = Field(default_factory=list)
    raw_data: dict[str, Any] = Field(default_factory=dict)


class MinerSnapshot(BaseModel):
    miner: str = "srbminer"
    miner_version: str | None = None
    uptime_seconds: float | None = None
    workloads: list[MinerWorkload] = Field(default_factory=list)
    devices: list[MinerDeviceIdentity] = Field(default_factory=list)
    gpu_errors: int | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)


class MinerHealth(BaseModel):
    is_alive: bool
    uptime_seconds: float | None = None
    error_message: str | None = None


class MinerStats(BaseModel):
    """Compatibility model for callers that consume one workload."""
    algorithm: str
    local_hashrate_hs: float | None = None
    accepted_shares: int | None = None
    rejected_shares: int | None = None
    invalid_shares: int | None = None
    gpu_errors: int | None = None


class HardwareSample(BaseModel):
    timestamp: datetime
    session_id: str
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


class MinerSample(BaseModel):
    timestamp: datetime
    session_id: str
    miner: str = "srbminer"
    raw_algorithm_name: str
    canonical_algorithm_id: str
    canonical_algorithm_name: str
    local_hashrate_hs: float | None = None
    accepted_shares: int | None = None
    rejected_shares: int | None = None
    invalid_shares: int | None = None
    miner_uptime_seconds: float | None = None
    gpu_errors: int | None = None
    device_ids: list[int] = Field(default_factory=list)
    raw_data: dict[str, Any] = Field(default_factory=dict)

    @property
    def algorithm(self) -> str:
        return self.canonical_algorithm_name


class SessionRecord(BaseModel):
    session_id: str
    miner: str = "srbminer"
    gpu_ids: list[int] = Field(default_factory=list)
    algorithm_ids: list[str] = Field(default_factory=list)
    raw_algorithm_names: list[str] = Field(default_factory=list)
    payout_coin: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    state: SessionState = SessionState.OBSERVE
    health: SessionHealth = SessionHealth.HEALTHY

    @property
    def algorithm(self) -> str:
        return self.algorithm_ids[0] if self.algorithm_ids else "unknown"


class ProfileScope(BaseModel):
    """Identity boundary for future profiles; M1 does not apply profiles."""
    gpu_id: int
    algorithm_id: str
    miner: str
    profile_name: str


class Event(BaseModel):
    timestamp: datetime
    event_type: EventType
    session_id: str | None = None
    severity: EventSeverity = EventSeverity.INFO
    source: str
    message: str
    metadata: dict[str, Any] | None = None
