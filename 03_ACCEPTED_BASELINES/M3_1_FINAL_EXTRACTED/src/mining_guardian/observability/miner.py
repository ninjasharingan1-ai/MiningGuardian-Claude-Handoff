"""Canonical miner evidence from one bounded HTTP acquisition, no health inference."""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
from pydantic import JsonValue

from mining_guardian.adapters.srbminer import (
    _UNIT_FACTORS,
    SRBMinerClient,
    _first,
    parse_srbminer_payload,
)
from mining_guardian.models import MinerSnapshot

from .models import Quality, RuntimeObservation, Source
from .payloads import MAX_PAYLOAD_BYTES, safe_endpoint, safe_payload
from .temporal import Clock, elapsed
from .values import numeric


@dataclass
class MinerAcquisition:
    observations: list[RuntimeObservation]
    snapshot: MinerSnapshot | None
    request_seconds: float


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def canonicalize_miner(payload: dict[str, Any], *, endpoint: str,
                       ingestion_time: datetime, correlation_id: UUID,
                       guardian_session_id: str | None) -> MinerAcquisition:
    redacted = safe_payload(payload)
    source_instance = safe_endpoint(endpoint)
    if not isinstance(redacted, dict):
        raise ValueError("payload_not_object")
    snapshot = parse_srbminer_payload(redacted)
    base: dict[str, Any] = {"source": Source.SRBMINER_HTTP, "source_instance": source_instance,
                           "ingestion_time": ingestion_time, "correlation_id": correlation_id,
                           "guardian_session_id": guardian_session_id}
    raw_record = RuntimeObservation(**base, signal="raw_payload", value=redacted,
        quality=Quality.UNKNOWN, provenance={"redaction": "secret_keys_and_endpoint_credentials",
        "interpretation": "raw_source_payload", "source_recording_time": "not_established",
        "process_incarnation": "unknown"})
    records = [raw_record]
    provenance: dict[str, JsonValue] = {"payload_observation_id": str(raw_record.observation_id),
                  "source_scope": "miner:srbminer", "process_incarnation": "unknown"}
    records.append(RuntimeObservation(**base, signal="api_availability", value=True,
        quality=Quality.VALID, provenance=provenance))
    uptime_raw = _first(payload, "uptime_seconds", "UptimeSeconds", "uptime", "Uptime", "mining_time")
    uptime, quality = numeric(uptime_raw)
    records.append(RuntimeObservation(**base, signal="uptime_seconds", value=uptime, unit="s",
        quality=quality, provenance=provenance))
    container = _first(payload, "workloads", "Workloads", "algorithms", "Algorithms")
    entries: list[tuple[str | None, Any]]
    if isinstance(container, list):
        entries = [(None, item) for item in container]
    elif isinstance(container, dict):
        entries = list(container.items())
    elif container is None:
        entries = [(None, payload)]
    else:
        entries = [(None, container)]
    for position, (fallback, raw) in enumerate(entries):
        context: dict[str, Any] = {**provenance, "payload_position": position,
                                   "position_is_identity": False}
        if not isinstance(raw, dict):
            records.append(RuntimeObservation(**base, signal="workload_parse", quality=Quality.CORRUPTED,
                                               provenance=context))
            continue
        wrapped = {"algorithms": {fallback: raw}} if fallback is not None else {"algorithms": [raw]}
        parsed = parse_srbminer_payload(wrapped)
        if not parsed.workloads:
            records.append(RuntimeObservation(**base, signal="workload_parse", quality=Quality.CORRUPTED,
                quality_metadata={"reason": "algorithm_identity_missing"}, provenance=context))
            continue
        workload = parsed.workloads[0]
        context["raw_algorithm_name"] = safe_payload(workload.raw_algorithm_name)
        context["miner_workload_id"] = safe_payload(raw.get("id"))
        context["device_namespace"] = "srbminer"
        raw_hashrate = _first(raw, "hashrate_hs", "hash_rate_hs", "HashRateHs", "HashRateHps", "hashrateHps", "hashrate", "HashRate", "hash_rate", "hashrate_khs", "hashrate_mhs", "hashrate_ghs", "hashrate_ths", "hashrate_phs")
        if isinstance(raw_hashrate, dict):
            raw_hashrate = raw_hashrate.get("1min")
        hashrate_quality = Quality.VALID if workload.hashrate_hs is not None else Quality.MISSING
        if workload.hashrate_hs is None and raw_hashrate is not None:
            _, numeric_quality = numeric(raw_hashrate)
            hashrate_quality = numeric_quality if numeric_quality != Quality.VALID else Quality.UNKNOWN
            unit = _first(raw, "hashrate_unit", "HashRateUnit", "unit")
            known_unit = isinstance(unit, str) and unit.strip().casefold() in _UNIT_FACTORS
            known_suffix = any(k in raw for k in ("hashrate_khs", "hashrate_mhs", "hashrate_ghs", "hashrate_ths", "hashrate_phs"))
            if numeric_quality == Quality.VALID and (known_unit or known_suffix):
                hashrate_quality = Quality.OUT_OF_RANGE
        records.append(RuntimeObservation(**base, signal="hashrate_hs", value=workload.hashrate_hs,
            unit="H/s", quality=hashrate_quality, provenance=context))
        shares = _first(raw, "shares", "Shares")
        if shares is not None and not isinstance(shares, dict):
            records.append(RuntimeObservation(**base, signal="shares_parse", quality=Quality.CORRUPTED,
                                               provenance=context))
        for name in ("total", "accepted", "rejected", "invalid"):
            counter = _first(raw, f"{name}_shares", f"{name.title()}Shares", name, name.title())
            if counter is None and isinstance(shares, dict):
                counter = _first(shares, name, name.title())
            value, quality = numeric(counter, integer=True)
            records.append(RuntimeObservation(**base, signal=f"{name}_shares", value=value,
                unit="count", quality=quality, provenance=context))
    return MinerAcquisition(records, snapshot, 0)


class MinerObserver:
    def __init__(self, client: SRBMinerClient, clock: Clock | None = None):
        self.client = client
        self.clock = clock or Clock()

    async def collect(self, correlation_id: UUID, guardian_session_id: str | None) -> MinerAcquisition:
        start = self.clock.monotonic()
        endpoint = f"{self.client.base_url}{self.client.api_path}"
        quality = Quality.SOURCE_UNAVAILABLE
        try:
            async with (
                asyncio.timeout(self.client.timeout),
                httpx.AsyncClient(timeout=self.client.timeout, transport=self.client._transport,
                                  trust_env=False, follow_redirects=False,
                                  headers={"Accept-Encoding": "identity"}) as client,
                client.stream("GET", endpoint) as response,
            ):
                response.raise_for_status()
                quality = Quality.CORRUPTED
                if response.headers.get("content-encoding", "identity").casefold() != "identity":
                    raise ValueError("compressed_payload_not_supported")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_PAYLOAD_BYTES:
                        raise ValueError("payload_byte_limit")
                    body.extend(chunk)
            received = self.clock.now()
            request_seconds = elapsed(start, self.clock.monotonic)
            quality = Quality.CORRUPTED
            payload = json.loads(body, object_pairs_hook=_unique_object)
            if not isinstance(payload, dict):
                raise ValueError("payload_not_object")
            result = canonicalize_miner(payload, endpoint=endpoint, ingestion_time=received,
                correlation_id=correlation_id, guardian_session_id=guardian_session_id)
            result.request_seconds = request_seconds
            return result
        except (httpx.HTTPError, ValueError, TypeError, OverflowError, RecursionError, TimeoutError) as exc:
            if isinstance(exc, (httpx.HTTPError, TimeoutError)):
                quality = Quality.SOURCE_UNAVAILABLE
            try:
                identity = safe_endpoint(endpoint)
            except ValueError:
                identity = None
            record = RuntimeObservation(source=Source.SRBMINER_HTTP, source_instance=identity,
                signal="api_availability", ingestion_time=self.clock.now(), correlation_id=correlation_id,
                guardian_session_id=guardian_session_id, quality=quality,
                quality_metadata={"error_type": type(exc).__name__})
            return MinerAcquisition([record], None, elapsed(start, self.clock.monotonic))
