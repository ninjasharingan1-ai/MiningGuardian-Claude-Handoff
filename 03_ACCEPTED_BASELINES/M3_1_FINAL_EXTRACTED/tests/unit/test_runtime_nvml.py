# ruff: noqa: N802 -- the fake implements the external NVML binding's exact API.
from types import SimpleNamespace
from uuid import uuid4

from mining_guardian.observability.models import Quality
from mining_guardian.observability.nvml import NVMLObserver


class NotSupportedError(Exception):
    pass


class NoPermissionError(Exception):
    pass


class Binding:
    NVML_TEMPERATURE_GPU = 0
    NVML_CLOCK_GRAPHICS = 0
    NVML_CLOCK_MEM = 1

    def __init__(self):
        self.power_calls = 0

    def nvmlDeviceGetHandleByIndex(self, index):
        return index

    def nvmlDeviceGetUUID(self, handle):
        return "GPU-real-source-id"

    def nvmlDeviceGetTemperature(self, *args):
        return float("nan")

    def nvmlDeviceGetUtilizationRates(self, handle):
        return SimpleNamespace(gpu=0, memory=101)

    def nvmlDeviceGetClockInfo(self, *args):
        return 1200

    def nvmlDeviceGetPowerUsage(self, handle):
        self.power_calls += 1
        raise NotSupportedError()

    def nvmlDeviceGetPowerManagementLimit(self, handle):
        raise NoPermissionError()

    def nvmlDeviceGetPerformanceState(self, handle):
        return 0

    def nvmlDeviceGetCurrentClocksThrottleReason(self, handle):
        return 0


def test_partial_failure_zero_identity_and_unsupported_cache():
    binding = Binding()
    observer = NVMLObserver(binding, lambda: True)
    cycle = uuid4()
    records = observer.collect(0, cycle, "guardian")
    by_signal = {r.signal: r for r in records}
    assert by_signal["throttle_reasons"].value == 0
    assert by_signal["throttle_reasons"].quality == Quality.VALID
    assert by_signal["temperature_c"].quality == Quality.CORRUPTED
    assert by_signal["utilization_memory"].quality == Quality.OUT_OF_RANGE
    assert by_signal["power_limit_w"].quality_metadata["capability"] == "no_permission"
    assert all(r.correlation_id == cycle and r.source_instance == "uuid:GPU-real-source-id" for r in records)
    assert all(r.observation_time is None and r.ingestion_time.tzinfo is not None for r in records)
    observer.collect(0, uuid4(), "guardian")
    assert binding.power_calls == 1


def test_unavailable_and_unknown_identity_never_invent_gpu_mapping():
    assert NVMLObserver(None, lambda: False).collect(0, uuid4(), None)[0].quality == Quality.SOURCE_UNAVAILABLE
    binding = Binding()
    binding.nvmlDeviceGetUUID = lambda handle: None
    records = NVMLObserver(binding, lambda: True).collect(0, uuid4(), None)
    assert all(r.source_instance is None for r in records)
    assert all(r.provenance["cross_source_mapping"] == "unknown" for r in records)
