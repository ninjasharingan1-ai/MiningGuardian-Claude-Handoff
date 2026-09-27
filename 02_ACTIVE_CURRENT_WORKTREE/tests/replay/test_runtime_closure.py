import json
import time
from datetime import timedelta
from pathlib import Path
from statistics import median
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text

from mining_guardian.adapters.srbminer import SRBMinerClient
from mining_guardian.observability.miner import MinerObserver
from mining_guardian.observability.models import Quality, Source
from mining_guardian.observability.nvml import NVMLObserver
from mining_guardian.observability.observer import RuntimeObserver
from mining_guardian.observability.payloads import safe_endpoint, safe_payload
from mining_guardian.observability.temporal import evaluate_freshness
from mining_guardian.storage.runtime_repository import RuntimeEvidenceRepository
from tests.unit.test_runtime_nvml import Binding, NotSupportedError
from tests.unit.test_runtime_observation import observation


def test_manipulated_source_order_stays_invalid_even_when_now_is_later():
    first = observation()
    future = observation(observation_time=first.ingestion_time + timedelta(seconds=1))
    assert evaluate_freshness(future, first.ingestion_time + timedelta(days=1)).quality == Quality.OUT_OF_RANGE
    bad_event = observation(event_time=first.ingestion_time, observation_time=first.ingestion_time - timedelta(seconds=1))
    assert evaluate_freshness(bad_event, first.ingestion_time).quality == Quality.OUT_OF_RANGE
    with pytest.raises(ValueError):
        safe_endpoint("not a host:3333")
    with pytest.raises(ValueError):
        safe_payload([[[[[[[[[[[[[[[[[[0]]]]]]]]]]]]]]]]]])


def test_unsupported_identity_and_fields_are_not_polled_forever():
    class UnsupportedIdentity(Binding):
        identity_calls = 0

        def nvmlDeviceGetUUID(self, handle):  # noqa: N802 -- external API
            self.identity_calls += 1
            raise NotSupportedError()

        def nvmlDeviceGetPciInfo(self, handle):  # noqa: N802 -- external API
            self.identity_calls += 1
            raise NotSupportedError()

    binding = UnsupportedIdentity()
    observer = NVMLObserver(binding, lambda: True)
    for _ in range(10):
        records = observer.collect(0, uuid4(), None)
        assert all(r.source_instance is None for r in records)
    assert binding.identity_calls == 2 and binding.power_calls == 1


@pytest.mark.asyncio
async def test_forged_correlation_cannot_poison_other_source():
    class ForgedHardware:
        def collect(self, *args):
            return [observation()]  # An unrelated acquisition is not accepted.

    class Sink:
        def save_cycle(self, records):
            self.records = records

    client = SRBMinerClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"algorithm": "pearlhash", "hashrate_hs": 0})))
    result = await RuntimeObserver(MinerObserver(client), ForgedHardware(), Sink()).collect_cycle("g")
    assert result.stored
    assert any(r.source == Source.NVML and r.quality == Quality.SOURCE_UNAVAILABLE for r in result.observations)
    assert any(r.signal == "hashrate_hs" and r.value == 0 for r in result.observations)
    assert all(r.correlation_id == result.context.correlation_id for r in result.observations)


@pytest.mark.asyncio
async def test_replay_long_session_cost_and_fault_recovery(tmp_path, capsys):
    payload = json.loads(Path("tests/fixtures/srbminer_3_6_4.json").read_text())
    request_count = 0

    def handle(request):
        nonlocal request_count
        request_count += 1
        if request_count % 25 == 0:
            return httpx.Response(503)
        payload["mining_time"] = request_count if request_count < 100 else request_count - 100
        return httpx.Response(200, json=payload)

    engine = create_engine(f"sqlite:///{(tmp_path / 'replay.db').as_posix()}")
    try:
        repository = RuntimeEvidenceRepository(engine)
        binding = Binding()
        observer = RuntimeObserver(MinerObserver(SRBMinerClient(transport=httpx.MockTransport(handle))),
            NVMLObserver(binding, lambda: True), repository)
        results = []
        saw_discontinuity = False
        first_id = None
        for index in range(250):
            result = await observer.collect_cycle("replay-guardian")
            assert result.stored
            if index == 0:
                first_id = result.context.correlation_id
            saw_discontinuity |= any(r.quality == Quality.RESET_OR_DISCONTINUOUS for r in result.observations)
            results.append(result.durations["cycle_seconds"])
        assert saw_discontinuity and request_count == 250
        assert binding.power_calls == 1
        assert observer.continuity.retained_streams <= 5
        assert repository.load_cycle(first_id)
        start = time.perf_counter()
        for _ in range(50):
            assert repository.load_cycle(result.context.correlation_id)
        average_read = (time.perf_counter() - start) / 50
        with engine.connect() as connection:
            count = connection.scalar(text("SELECT count(*) FROM m3_runtime_observations_v1"))
            byte_count = connection.scalar(text("SELECT sum(length(payload_json)) FROM m3_runtime_observations_v1"))
            plan = connection.execute(text("EXPLAIN QUERY PLAN SELECT * FROM m3_runtime_observations_v1 WHERE correlation_id = :id"), {"id": str(result.context.correlation_id)}).all()
            assert any("INDEX" in str(row) for row in plan)
        # No timing assertion that depends on host load; report measured offline cost.
        with capsys.disabled():
            print(f"M3.1_REPLAY cycles=250 records={count} payload_bytes={byte_count} median_cycle_ms={median(results)*1000:.3f} max_cycle_ms={max(results)*1000:.3f} indexed_read_ms={average_read*1000:.3f} cached_unsupported_calls={binding.power_calls}")
    finally:
        engine.dispose()
