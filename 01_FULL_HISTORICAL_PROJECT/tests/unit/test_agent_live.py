import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from mining_guardian.adapters.srbminer import parse_srbminer_payload
from mining_guardian.agent.live import LiveWorldStateBuilder
from mining_guardian.agent.temporal import (
    FreshnessLevel,
    GuardianSessionStatus,
    MinerReachability,
    ObservationOrigin,
)
from mining_guardian.core import AlgorithmRegistry
from mining_guardian.models import (
    HardwareSample,
    MinerSnapshot,
    MinerWorkload,
    SessionRecord,
)
from mining_guardian.storage import SessionRepository
from mining_guardian.storage.schema import HardwareSampleDB, MinerSampleDB, SessionDB


class CountingMinerClient:
    def __init__(self, snapshot: MinerSnapshot | None):
        self._snapshot = snapshot
        self.calls = 0

    async def snapshot(self) -> MinerSnapshot | None:
        self.calls += 1
        return self._snapshot


class CountingNVMLClient:
    def __init__(self, sample: HardwareSample | None):
        self._sample = sample
        self.calls = 0

    def read_telemetry(self, gpu_index: int = 0) -> HardwareSample | None:
        self.calls += 1
        if self._sample is None:
            return None
        return self._sample.model_copy(deep=True)


def _counts(session) -> tuple[int, int, int]:
    return (
        session.scalar(select(func.count()).select_from(SessionDB)) or 0,
        session.scalar(select(func.count()).select_from(MinerSampleDB)) or 0,
        session.scalar(select(func.count()).select_from(HardwareSampleDB)) or 0,
    )


@pytest.mark.asyncio
async def test_live_probe_is_ephemeral_read_only_and_normalizes_algorithm(temp_db):
    started = datetime.now(UTC) - timedelta(minutes=10)
    ended = started + timedelta(seconds=61)
    snapshot = MinerSnapshot(
        miner="srbminer",
        miner_version="3.6.4",
        uptime_seconds=600,
        workloads=[
            MinerWorkload(
                raw_algorithm_name="pearlhash",
                hashrate_hs=32_459_610_144_862.57,
                accepted_shares=1,
                rejected_shares=0,
                device_ids=[1],
            )
        ],
    )
    hardware = HardwareSample(
        timestamp=datetime.now(UTC),
        session_id="",
        gpu_id=0,
        temperature_c=61,
        utilization_gpu=96,
        power_w=35,
    )
    miner_client = CountingMinerClient(snapshot)
    nvml_client = CountingNVMLClient(hardware)

    with temp_db.get_session() as session:
        AlgorithmRegistry(session)
        SessionRepository(session).create(
            SessionRecord(
                session_id="last_session",
                miner="srbminer",
                start_time=started,
                end_time=ended,
                gpu_ids=[0],
                algorithm_ids=["pearlpow"],
                raw_algorithm_names=["pearlhash"],
            )
        )
        before = _counts(session)
        registry = AlgorithmRegistry(session, seed_builtins=False)
        state = await LiveWorldStateBuilder(
            miner_client,
            nvml_client,
            registry,
            SessionRepository(session),
            gpu_index=0,
        ).build()
        after = _counts(session)

        assert before == after
        assert miner_client.calls == 1
        assert nvml_client.calls == 1
        assert state.observation_origin is ObservationOrigin.LIVE_PROBE
        assert state.freshness is FreshnessLevel.FRESH
        assert state.facts.miner_reachability is MinerReachability.REACHABLE
        assert state.facts.miner_version == "3.6.4"
        assert state.facts.guardian_session_status is GuardianSessionStatus.ENDED
        assert state.derived.session_age_seconds is None
        assert state.derived.session_duration_seconds == 61
        workload = state.facts.workloads[0]
        assert workload.raw_algorithm_name == "pearlhash"
        assert workload.canonical_algorithm_id == "pearlpow"
        assert workload.canonical_algorithm_name == "PearlPow"
        assert workload.local_hashrate_hs == 32_459_610_144_862.57
        assert workload.device_ids == [1]
        assert state.facts.gpus[0].gpu_id == 0


@pytest.mark.asyncio
async def test_live_probe_without_persisted_session_has_unknown_guardian_status(temp_db):
    snapshot = MinerSnapshot(
        miner="srbminer",
        miner_version="3.6.4",
        workloads=[MinerWorkload(raw_algorithm_name="pearlhash", hashrate_hs=1.0)],
    )
    hardware = HardwareSample(
        timestamp=datetime.now(UTC),
        session_id="",
        gpu_id=0,
        temperature_c=50,
    )
    with temp_db.get_session() as session:
        AlgorithmRegistry(session)
        state = await LiveWorldStateBuilder(
            CountingMinerClient(snapshot),
            CountingNVMLClient(hardware),
            AlgorithmRegistry(session, seed_builtins=False),
            SessionRepository(session),
        ).build()
        assert state.facts.session_id is None
        assert state.facts.guardian_session_status is GuardianSessionStatus.UNKNOWN
        assert state.facts.miner_reachability is MinerReachability.REACHABLE


@pytest.mark.asyncio
async def test_live_probe_unreachable_miner_does_not_claim_fresh_overall(temp_db):
    hardware = HardwareSample(
        timestamp=datetime.now(UTC),
        session_id="",
        gpu_id=0,
        temperature_c=50,
    )
    with temp_db.get_session() as session:
        AlgorithmRegistry(session)
        state = await LiveWorldStateBuilder(
            CountingMinerClient(None),
            CountingNVMLClient(hardware),
            AlgorithmRegistry(session, seed_builtins=False),
            SessionRepository(session),
        ).build()
        assert state.facts.miner_reachability is MinerReachability.UNREACHABLE
        assert state.miner_freshness is FreshnessLevel.UNKNOWN
        assert state.hardware_freshness is FreshnessLevel.FRESH
        assert state.freshness is FreshnessLevel.UNKNOWN
        assert not state.context_validity.is_current_state_usable


@pytest.mark.asyncio
async def test_real_srbminer_364_fixture_version_reaches_live_world_state(temp_db):
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "srbminer_3_6_4.json"
    snapshot = parse_srbminer_payload(json.loads(fixture.read_text(encoding="utf-8")))
    hardware = HardwareSample(
        timestamp=datetime.now(UTC),
        session_id="",
        gpu_id=0,
        temperature_c=61,
        utilization_gpu=96,
        power_w=35,
    )
    with temp_db.get_session() as session:
        AlgorithmRegistry(session)
        state = await LiveWorldStateBuilder(
            CountingMinerClient(snapshot),
            CountingNVMLClient(hardware),
            AlgorithmRegistry(session, seed_builtins=False),
            SessionRepository(session),
        ).build()
        assert state.facts.miner_version == "3.6.4"
        assert state.facts.workloads[0].raw_algorithm_name == "pearlhash"
        assert state.facts.workloads[0].canonical_algorithm_name == "PearlPow"
