from datetime import datetime
from typing import Protocol

from ..logging import get_logger
from ..models import HardwareSample

logger = get_logger(__name__)


class NVMLTelemetryClient(Protocol):
    """Read-only telemetry interface used by the hardware collector."""

    def read_telemetry(self, gpu_index: int = 0) -> HardwareSample | None: ...


class HardwareCollector:
    def __init__(self, nvml_client: NVMLTelemetryClient, gpu_index: int = 0):
        self.nvml_client = nvml_client
        self.gpu_index = gpu_index

    async def collect(
        self,
        session_id: str,
        *,
        miner: str | None = None,
        algorithm_ids: list[str] | None = None,
    ) -> HardwareSample | None:
        sample = self.nvml_client.read_telemetry(self.gpu_index)
        if sample is None:
            logger.warning("hardware_sample_collection_failed", gpu_id=self.gpu_index)
            return None
        sample.session_id = session_id
        sample.timestamp = datetime.now()
        sample.miner = miner
        sample.algorithm_ids = algorithm_ids or []
        return sample
