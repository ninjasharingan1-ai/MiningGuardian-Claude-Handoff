from datetime import datetime
from typing import Any

from ..enums import CapabilityState
from ..logging import get_logger
from ..models import GPUCapabilities, GPUInfo, HardwareSample

logger = get_logger(__name__)

try:
    import pynvml
except ImportError:
    pynvml = None


def _capability_from_exception(exc: Exception) -> CapabilityState:
    name = type(exc).__name__.casefold()
    text = str(exc).casefold()
    if "permission" in name or "permission" in text or "no_permission" in name:
        return CapabilityState.NO_PERMISSION
    if "notsupported" in name or "not supported" in text:
        return CapabilityState.UNSUPPORTED
    return CapabilityState.UNKNOWN


class NVMLClient:
    """Read-only NVML telemetry adapter."""

    def __init__(self) -> None:
        self.initialized = False
        self._init_nvml()

    def _init_nvml(self) -> None:
        if pynvml is None:
            logger.warning("nvml_import_unavailable")
            return
        try:
            pynvml.nvmlInit()
            self.initialized = True
        except Exception as exc:
            logger.warning("nvml_init_error", error=str(exc))

    def _probe(self, call) -> CapabilityState:
        try:
            call()
            return CapabilityState.SUPPORTED
        except Exception as exc:
            return _capability_from_exception(exc)

    def probe_capabilities(self, gpu_index: int = 0) -> GPUCapabilities:
        capabilities = GPUCapabilities()
        if not self.initialized or pynvml is None:
            return capabilities
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_index)
        except Exception as exc:
            logger.warning("nvml_handle_error", error=str(exc))
            return capabilities

        capabilities.can_read_temperature = self._probe(
            lambda: pynvml.nvmlDeviceGetTemperature(handle, getattr(pynvml, "NVML_TEMPERATURE_GPU", 0))
        )
        capabilities.can_read_clocks = self._probe(
            lambda: pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_GRAPHICS)
        )
        capabilities.can_read_power = self._probe(lambda: pynvml.nvmlDeviceGetPowerUsage(handle))
        capabilities.can_read_utilization = self._probe(lambda: pynvml.nvmlDeviceGetUtilizationRates(handle))
        capabilities.can_read_throttle_reasons = self._probe(
            lambda: pynvml.nvmlDeviceGetCurrentClocksThrottleReason(handle)
        )
        return capabilities

    def get_gpu_info(self, gpu_index: int = 0) -> GPUInfo | None:
        if not self.initialized or pynvml is None:
            return None
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_index)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="replace")
            return GPUInfo(
                gpu_index=gpu_index,
                name=str(name),
                capabilities=self.probe_capabilities(gpu_index),
            )
        except Exception as exc:
            logger.warning("nvml_gpu_info_error", error=str(exc))
            return None

    def read_telemetry(self, gpu_index: int = 0) -> HardwareSample | None:
        if not self.initialized or pynvml is None:
            return None
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_index)
        except Exception as exc:
            logger.warning("nvml_handle_error", error=str(exc))
            return None

        sample = HardwareSample(timestamp=datetime.now(), session_id="", gpu_id=gpu_index)
        capability_states: dict[str, CapabilityState] = {}

        def read(field: str, call, transform=lambda value: value) -> Any:
            try:
                value = transform(call())
                capability_states[field] = CapabilityState.SUPPORTED
                return value
            except Exception as exc:
                capability_states[field] = _capability_from_exception(exc)
                return None

        sample.temperature_c = read(
            "temperature",
            lambda: pynvml.nvmlDeviceGetTemperature(handle, getattr(pynvml, "NVML_TEMPERATURE_GPU", 0)),
            float,
        )
        try:
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            sample.utilization_gpu = float(util.gpu)
            sample.utilization_memory = float(util.memory)
            capability_states["utilization"] = CapabilityState.SUPPORTED
        except Exception as exc:
            capability_states["utilization"] = _capability_from_exception(exc)

        sample.core_clock_mhz = read(
            "core_clock", lambda: pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_GRAPHICS), float
        )
        sample.memory_clock_mhz = read(
            "memory_clock", lambda: pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM), float
        )
        sample.power_w = read("power", lambda: pynvml.nvmlDeviceGetPowerUsage(handle), lambda value: value / 1000.0)
        sample.power_limit_w = read(
            "power_limit", lambda: pynvml.nvmlDeviceGetPowerManagementLimit(handle), lambda value: value / 1000.0
        )
        sample.performance_state = read(
            "performance_state", lambda: pynvml.nvmlDeviceGetPerformanceState(handle), lambda value: f"P{value}"
        )
        sample.throttle_reasons = read(
            "throttle_reasons",
            lambda: pynvml.nvmlDeviceGetCurrentClocksThrottleReason(handle),
            lambda value: str(value) if value else None,
        )
        sample.capability_states = capability_states
        return sample

    def close(self) -> None:
        if self.initialized and pynvml is not None:
            try:
                pynvml.nvmlShutdown()
            except Exception as exc:
                logger.warning("nvml_shutdown_error", error=str(exc))
            finally:
                self.initialized = False
