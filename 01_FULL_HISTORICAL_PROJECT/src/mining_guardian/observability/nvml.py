"""Read-only canonical NVML observations, with an injected binding for offline tests."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mining_guardian.adapters.nvml import _capability_from_exception
from mining_guardian.enums import CapabilityState

from .models import Quality, RuntimeObservation, Source
from .temporal import Clock
from .values import numeric, raw_scalar


class NVMLObserver:
    def __init__(self, binding: Any, available: Callable[[], bool], clock: Clock | None = None):
        self.binding = binding
        self.available = available
        self.clock = clock or Clock()
        self._unsupported: set[tuple[str | None, str]] = set()
        self._unsupported_identity: set[tuple[int, str]] = set()

    def collect(self, gpu_index: int, correlation_id: UUID,
                guardian_session_id: str | None) -> list[RuntimeObservation]:
        api = self.binding
        try:
            if api is None or not self.available():
                raise RuntimeError("nvml_unavailable")
            handle = api.nvmlDeviceGetHandleByIndex(gpu_index)
        except Exception as exc:
            self._unsupported.clear()
            self._unsupported_identity.clear()
            return [RuntimeObservation(source=Source.NVML, signal="availability", value=None,
                        ingestion_time=self.clock.now(), correlation_id=correlation_id,
                        guardian_session_id=guardian_session_id, quality=Quality.SOURCE_UNAVAILABLE,
                        quality_metadata={"error_type": type(exc).__name__})]

        identity: str | None = None
        identity_basis = "unavailable"
        for name, getter in [("uuid", lambda: api.nvmlDeviceGetUUID(handle)),
                             ("pci", lambda: api.nvmlDeviceGetPciInfo(handle).busId)]:
            if (gpu_index, name) in self._unsupported_identity:
                continue
            try:
                candidate = getter()
                if isinstance(candidate, bytes):
                    candidate = candidate.decode("utf-8", errors="strict")
                if isinstance(candidate, str) and candidate.strip() and len(candidate) <= 512:
                    identity = f"{name}:{candidate}"
                    identity_basis = name
                    break
            except Exception as exc:
                if _capability_from_exception(exc) == CapabilityState.UNSUPPORTED:
                    if len(self._unsupported_identity) >= 256:
                        self._unsupported_identity.clear()
                    self._unsupported_identity.add((gpu_index, name))
                continue  # Identity remains explicitly unproven; index is not substituted.

        utilization: Any = None

        def util(field: str) -> Any:
            nonlocal utilization
            if utilization is None:
                utilization = api.nvmlDeviceGetUtilizationRates(handle)
            return getattr(utilization, field)

        fields = [
            ("temperature_c", "degC", lambda: api.nvmlDeviceGetTemperature(handle, api.NVML_TEMPERATURE_GPU), -273.15, None, False, 1),
            ("utilization_gpu", "%", lambda: util("gpu"), 0, 100, False, 1),
            ("utilization_memory", "%", lambda: util("memory"), 0, 100, False, 1),
            ("core_clock_mhz", "MHz", lambda: api.nvmlDeviceGetClockInfo(handle, api.NVML_CLOCK_GRAPHICS), 0, None, False, 1),
            ("memory_clock_mhz", "MHz", lambda: api.nvmlDeviceGetClockInfo(handle, api.NVML_CLOCK_MEM), 0, None, False, 1),
            ("power_w", "W", lambda: api.nvmlDeviceGetPowerUsage(handle), 0, None, False, 1000),
            ("power_limit_w", "W", lambda: api.nvmlDeviceGetPowerManagementLimit(handle), 0, None, False, 1000),
            ("performance_state", "pstate", lambda: api.nvmlDeviceGetPerformanceState(handle), 0, None, True, 1),
            ("throttle_reasons", "bitmask", lambda: api.nvmlDeviceGetCurrentClocksThrottleReason(handle), 0, 2**64 - 1, True, 1),
        ]
        records = []
        for signal, unit, getter, minimum, maximum, integer, divisor in fields:
            raw = None
            error_type = None
            # This fallback is only an in-process retry-suppression key, never domain identity.
            cache_key = identity if identity is not None else f"unverified-index:{gpu_index}"
            cached = (cache_key, signal) in self._unsupported
            capability = CapabilityState.UNSUPPORTED if cached else CapabilityState.UNKNOWN
            value = None
            quality = Quality.MISSING
            if not cached:
                try:
                    raw = getter()
                    capability = CapabilityState.SUPPORTED
                    value, quality = numeric(raw, minimum=minimum, maximum=maximum, integer=integer)
                    if value is not None and divisor != 1:
                        value /= divisor
                except Exception as exc:
                    capability = _capability_from_exception(exc)
                    error_type = type(exc).__name__
                    quality = Quality.SOURCE_UNAVAILABLE if capability == CapabilityState.UNKNOWN else Quality.MISSING
                    if capability == CapabilityState.UNSUPPORTED:
                        if len(self._unsupported) >= 256:
                            self._unsupported.clear()
                        self._unsupported.add((cache_key, signal))
            records.append(RuntimeObservation(
                source=Source.NVML, source_instance=identity, signal=signal, value=value, unit=unit,
                ingestion_time=self.clock.now(), correlation_id=correlation_id,
                guardian_session_id=guardian_session_id, quality=quality,
                quality_metadata={"capability": capability.value, "cached_unsupported": cached,
                                  "error_type": error_type},
                provenance={"identity_basis": identity_basis, "configured_index": gpu_index,
                            "raw_value": raw_scalar(raw), "cross_source_mapping": "unknown",
                            "source_recording_time": "not_provided_by_nvml"},
            ))
        return records
