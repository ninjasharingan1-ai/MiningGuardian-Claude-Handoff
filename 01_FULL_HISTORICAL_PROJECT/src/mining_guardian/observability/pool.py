"""Pool metadata reported by the miner; unestablished field units remain unknown."""

from contextlib import suppress
from typing import Any

from .models import Quality, RuntimeObservation, Source
from .payloads import safe_endpoint


def pool_observations(raw_record: RuntimeObservation) -> list[RuntimeObservation]:
    if raw_record.source != Source.SRBMINER_HTTP or raw_record.signal != "raw_payload":
        raise ValueError("pool promotion requires miner raw-payload provenance")
    payload = raw_record.value
    if not isinstance(payload, dict):
        return []
    container = next((payload[k] for k in ("workloads", "Workloads", "algorithms", "Algorithms") if k in payload), None)
    entries = list(container.values()) if isinstance(container, dict) else container
    if not isinstance(entries, list):
        entries = [payload]
    records = []
    for position, workload in enumerate(entries):
        if not isinstance(workload, dict):
            continue
        pool = workload.get("pool")
        identity = None
        endpoint = pool.get("pool") if isinstance(pool, dict) else None
        if isinstance(endpoint, str):
            with suppress(ValueError):
                identity = safe_endpoint(endpoint)
        base: dict[str, Any] = {
            "source": Source.POOL_DATA_FROM_MINER, "source_instance": identity,
            "ingestion_time": raw_record.ingestion_time,
            "correlation_id": raw_record.correlation_id,
            "guardian_session_id": raw_record.guardian_session_id,
            "provenance": {"payload_observation_id": str(raw_record.observation_id),
                           "miner_endpoint": raw_record.source_instance,
                           "payload_position": position, "miner_workload_id": workload.get("id"),
                           "interpretation": "miner_reported_not_independent_pool_probe"},
        }
        if pool is not None and not isinstance(pool, dict):
            records.append(RuntimeObservation(**base, signal="pool_parse", value=pool,
                                               quality=Quality.CORRUPTED))
            continue
        pool = pool if isinstance(pool, dict) else {}
        records.append(RuntimeObservation(**base, signal="endpoint", value=identity,
                                           quality=Quality.VALID if identity else Quality.MISSING))
        for field in ("time_connected", "uptime", "difficulty", "last_job_received", "latency"):
            records.append(RuntimeObservation(**base, signal=field, value=pool.get(field),
                quality=Quality.UNKNOWN if field in pool else Quality.MISSING,
                quality_metadata={"reason": "unit_and_timing_contract_not_established_in_repository"}))
    return records
