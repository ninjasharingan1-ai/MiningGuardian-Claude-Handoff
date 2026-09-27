"""One-way canonical GPU evidence projection for unchanged legacy consumers."""

from mining_guardian.enums import CapabilityState
from mining_guardian.models import HardwareSample

from .models import Quality, RuntimeObservation, Source


def legacy_hardware(records: list[RuntimeObservation], *, gpu_index: int,
                    session_id: str, algorithm_ids: list[str]) -> HardwareSample | None:
    gpu = [r for r in records if r.source == Source.NVML and r.signal != "availability"]
    if not gpu:
        return None
    # Explicit projection to the existing local-naive legacy format; no historical rewrite.
    sample = HardwareSample(timestamp=gpu[-1].ingestion_time.astimezone().replace(tzinfo=None),
                            session_id=session_id, gpu_id=gpu_index, miner="srbminer",
                            algorithm_ids=algorithm_ids)
    for record in gpu:
        capability = record.quality_metadata.get("capability")
        if isinstance(capability, str):
            legacy_key = {"temperature_c": "temperature", "core_clock_mhz": "core_clock",
                          "memory_clock_mhz": "memory_clock", "power_w": "power",
                          "power_limit_w": "power_limit"}.get(record.signal, record.signal)
            sample.capability_states[legacy_key] = CapabilityState(capability)
        if record.quality in (Quality.CORRUPTED, Quality.OUT_OF_RANGE, Quality.SOURCE_UNAVAILABLE, Quality.MISSING):
            continue
        if record.signal == "performance_state" and record.value is not None:
            sample.performance_state = f"P{record.value}"
        elif record.signal == "throttle_reasons" and record.value is not None:
            sample.throttle_reasons = str(record.value)
        elif (record.signal in {"temperature_c", "utilization_gpu", "utilization_memory", "core_clock_mhz", "memory_clock_mhz", "power_w", "power_limit_w"}
              and isinstance(record.value, (int, float)) and not isinstance(record.value, bool)):
            setattr(sample, record.signal, record.value)
    return sample
