from datetime import datetime, timedelta

from mining_guardian.agent.context import ContextBuilder, WorkingMemoryBuilder, WorldStateBuilder
from mining_guardian.agent.models import AgentWorkingMemory
from mining_guardian.core import AlgorithmRegistry
from mining_guardian.enums import CapabilityState
from mining_guardian.models import HardwareSample, MinerSample, SessionRecord
from mining_guardian.storage import (
    AgentDecisionRepository,
    AgentLessonRepository,
    HardwareSampleRepository,
    MinerSampleRepository,
    SessionRepository,
)


def _seed_session(temp_db, *, samples: int = 3) -> tuple[str, datetime]:
    started = datetime(2026, 9, 16, 0, 0, 0)
    record = SessionRecord(
        session_id="session_agent_context",
        miner="srbminer",
        gpu_ids=[0],
        algorithm_ids=["pearlpow"],
        raw_algorithm_names=["pearlhash"],
        start_time=started,
    )
    with temp_db.get_session() as session:
        AlgorithmRegistry(session)
        SessionRepository(session).create(record)
        miner_repo = MinerSampleRepository(session)
        hardware_repo = HardwareSampleRepository(session)
        for index in range(samples):
            timestamp = started + timedelta(seconds=60 * index)
            miner_repo.create(
                MinerSample(
                    timestamp=timestamp,
                    session_id=record.session_id,
                    miner="srbminer",
                    raw_algorithm_name="pearlhash",
                    canonical_algorithm_id="pearlpow",
                    canonical_algorithm_name="PearlPow",
                    local_hashrate_hs=30_000_000_000_000 + index * 1_000_000_000_000,
                    accepted_shares=10 + index,
                    rejected_shares=1,
                    miner_uptime_seconds=60.0 * index,
                    gpu_errors=0,
                    device_ids=[1],
                    raw_data={"miner_version": "3.6.4"},
                )
            )
            hardware_repo.create(
                HardwareSample(
                    timestamp=timestamp,
                    session_id=record.session_id,
                    gpu_id=0,
                    miner="srbminer",
                    algorithm_ids=["pearlpow"],
                    temperature_c=60.0 + index,
                    utilization_gpu=95.0,
                    utilization_memory=20.0,
                    core_clock_mhz=1650.0,
                    memory_clock_mhz=5871.0,
                    power_w=35.0,
                    power_limit_w=50.0,
                    performance_state="P0",
                    throttle_reasons="none",
                    capability_states={"temperature": CapabilityState.SUPPORTED},
                )
            )
    return record.session_id, started


def _builders(temp_db):
    session = temp_db.SessionLocal()
    session_repo = SessionRepository(session)
    miner_repo = MinerSampleRepository(session)
    hardware_repo = HardwareSampleRepository(session)
    world = WorldStateBuilder(session_repo, miner_repo, hardware_repo)
    context = ContextBuilder(session_repo, miner_repo, hardware_repo)
    working = WorkingMemoryBuilder(
        world,
        context,
        AgentDecisionRepository(session),
        AgentLessonRepository(session),
    )
    return session, world, context, working


def test_world_state_uses_latest_measured_facts_and_session_age(temp_db):
    session_id, started = _seed_session(temp_db)
    db_session, world_builder, _, _ = _builders(temp_db)
    try:
        state = world_builder.build(session_id, now=started + timedelta(minutes=3))
        assert state.facts.session_id == session_id
        assert state.facts.miner == "srbminer"
        assert state.facts.miner_version == "3.6.4"
        assert state.facts.session_state.value == "observe"
        assert state.facts.session_health.value == "healthy"
        assert state.derived.session_age_seconds == 180.0
        assert len(state.facts.workloads) == 1
        workload = state.facts.workloads[0]
        assert workload.raw_algorithm_name == "pearlhash"
        assert workload.canonical_algorithm_id == "pearlpow"
        assert workload.canonical_algorithm_name == "PearlPow"
        assert workload.local_hashrate_hs == 32_000_000_000_000
        assert workload.device_ids == [1]
        assert state.facts.gpus[0].gpu_id == 0
        assert state.facts.gpus[0].temperature_c == 62.0
        assert state.facts.gpus[0].capability_states["temperature"] is CapabilityState.SUPPORTED
    finally:
        db_session.close()


def test_world_state_preserves_missing_values(temp_db):
    started = datetime(2026, 9, 16, 1, 0, 0)
    record = SessionRecord(
        session_id="session_missing",
        miner="srbminer",
        start_time=started,
        algorithm_ids=["pearlpow"],
    )
    with temp_db.get_session() as session:
        AlgorithmRegistry(session)
        SessionRepository(session).create(record)
        MinerSampleRepository(session).create(
            MinerSample(
                timestamp=started,
                session_id=record.session_id,
                raw_algorithm_name="pearlhash",
                canonical_algorithm_id="pearlpow",
                canonical_algorithm_name="PearlPow",
            )
        )
    db_session, world_builder, _, _ = _builders(temp_db)
    try:
        state = world_builder.build(record.session_id, now=started + timedelta(seconds=10))
        assert state.facts.workloads[0].local_hashrate_hs is None
        assert "workloads.pearlpow.hashrate_hs" in state.missing_signals
        assert "gpu_telemetry" in state.missing_signals
        assert "miner_version" in state.missing_signals
    finally:
        db_session.close()


def test_context_windows_keep_hashrate_in_hs_and_compute_simple_trends(temp_db):
    session_id, started = _seed_session(temp_db)
    db_session, _, context_builder, _ = _builders(temp_db)
    try:
        windows = context_builder.build(session_id, now=started + timedelta(minutes=3))
        labels = {window.label for window in windows}
        assert {"5m", "30m", "6h", "current_session"} <= labels
        five_minute = next(window for window in windows if window.label == "5m")
        workload = five_minute.workloads[0]
        assert workload.algorithm_id == "pearlpow"
        assert workload.raw_algorithm_names == ["pearlhash"]
        assert workload.mean_hashrate_hs == 31_000_000_000_000
        assert workload.min_hashrate_hs == 30_000_000_000_000
        assert workload.max_hashrate_hs == 32_000_000_000_000
        assert round(workload.hashrate_slope_hs_per_second or 0, 2) == round(
            2_000_000_000_000 / 120,
            2,
        )
        assert workload.accepted_share_delta == 2
        assert workload.rejected_share_delta == 0
        gpu = five_minute.gpus[0]
        assert gpu.mean_temperature_c == 61.0
        assert gpu.max_temperature_c == 62.0
        assert gpu.mean_power_w == 35.0
        assert gpu.missing_data_fraction == 0.0
        assert workload.missing_hashrate_fraction == 0.0
        assert workload.error_delta == 0
    finally:
        db_session.close()


def test_context_window_requires_two_distinct_telemetry_timestamps(temp_db):
    session_id, started = _seed_session(temp_db, samples=1)
    db_session, _, context_builder, _ = _builders(temp_db)
    try:
        assert context_builder.build(session_id, now=started + timedelta(minutes=1)) == []
    finally:
        db_session.close()


def test_context_keeps_different_algorithms_separate(temp_db):
    session_id, started = _seed_session(temp_db, samples=2)
    with temp_db.get_session() as session:
        registry = AlgorithmRegistry(session)
        other, _ = registry.resolve("FutureHash", scope_type="miner", scope_name="srbminer")
        assert other is not None
        repo = MinerSampleRepository(session)
        for index in range(2):
            repo.create(
                MinerSample(
                    timestamp=started + timedelta(seconds=60 * index),
                    session_id=session_id,
                    raw_algorithm_name="FutureHash",
                    canonical_algorithm_id=other.algorithm_id,
                    canonical_algorithm_name=other.canonical_name,
                    local_hashrate_hs=1_000 + index * 100,
                )
            )
    db_session, _, context_builder, _ = _builders(temp_db)
    try:
        window = next(
            item
            for item in context_builder.build(session_id, now=started + timedelta(minutes=2))
            if item.label == "5m"
        )
        assert {item.algorithm_id for item in window.workloads} == {
            "pearlpow",
            other.algorithm_id,
        }
        pearl = next(item for item in window.workloads if item.algorithm_id == "pearlpow")
        future = next(item for item in window.workloads if item.algorithm_id == other.algorithm_id)
        assert pearl.mean_hashrate_hs > 1_000_000_000_000
        assert future.mean_hashrate_hs == 1_050
    finally:
        db_session.close()


def test_working_memory_is_structured_and_serializable(temp_db):
    session_id, started = _seed_session(temp_db)
    db_session, _, _, working_builder = _builders(temp_db)
    try:
        memory = working_builder.build(session_id, now=started + timedelta(minutes=3))
        encoded = memory.model_dump_json()
        decoded = AgentWorkingMemory.model_validate_json(encoded)
        assert decoded.world_state.facts.session_id == session_id
        assert decoded.world_state.facts.workloads[0].canonical_algorithm_id == "pearlpow"
        assert decoded.context_windows
        assert decoded.recent_decisions == []
    finally:
        db_session.close()
