import asyncio
import os
from datetime import datetime
from pathlib import Path

from mining_guardian.collectors import HardwareCollector, MinerCollector
from mining_guardian.core import AlgorithmRegistry, SessionManager
from mining_guardian.enums import EventType
from mining_guardian.models import Event, HardwareSample, MinerWorkload
from mining_guardian.storage import (
    Database,
    EventRepository,
    HardwareSampleRepository,
    MinerSampleRepository,
    SessionRepository,
)
from tests.fixtures.fakes import FakeNVMLClient, FakeSRBMinerClient


def test_session_known_algorithm_updates_identity(temp_db):
    manager = SessionManager()
    record = manager.create_session(gpu_ids=[0])
    with temp_db.get_session() as session:
        session_repo = SessionRepository(session)
        session_repo.create(record)
        registry = AlgorithmRegistry(session)
        collector = MinerCollector(FakeSRBMinerClient(algorithm="pearlhash"), registry)
        samples = asyncio.run(collector.collect(record.session_id))
        ids = [sample.canonical_algorithm_id for sample in samples]
        raws = [sample.raw_algorithm_name for sample in samples]
        manager.update_algorithms(ids, raws)
        session_repo.update_algorithms(record.session_id, ids, raws)
        stored = session_repo.get_by_id(record.session_id)
        assert stored is not None
        assert stored.algorithm_ids == ["pearlpow"]
        assert stored.raw_algorithm_names == ["pearlhash"]


def test_same_gpu_miner_different_algorithms_distinguishable(temp_db):
    manager = SessionManager()
    record = manager.create_session(gpu_ids=[0])
    with temp_db.get_session() as session:
        SessionRepository(session).create(record)
        registry = AlgorithmRegistry(session)
        fake = FakeSRBMinerClient(
            workloads=[
                MinerWorkload(raw_algorithm_name="pearlhash", hashrate_hs=10, device_ids=[0]),
                MinerWorkload(raw_algorithm_name="FutureAlgo", hashrate_hs=20, device_ids=[0]),
            ]
        )
        samples = asyncio.run(MinerCollector(fake, registry).collect(record.session_id))
        repo = MinerSampleRepository(session)
        for sample in samples:
            repo.create(sample)
        stored = repo.get_all_by_session(record.session_id)
        assert len(stored) == 2
        assert stored[0].canonical_algorithm_id != stored[1].canonical_algorithm_id
        assert {sample.miner for sample in stored} == {"srbminer"}
        assert {tuple(sample.device_ids) for sample in stored} == {(0,)}


def test_unknown_algorithm_telemetry_collection_and_persistence(temp_db):
    record = SessionManager().create_session(gpu_ids=[0])
    with temp_db.get_session() as session:
        SessionRepository(session).create(record)
        registry = AlgorithmRegistry(session)
        collector = MinerCollector(FakeSRBMinerClient(algorithm="UnknownFuture"), registry)
        samples = asyncio.run(collector.collect(record.session_id))
        assert len(samples) == 1
        assert samples[0].raw_algorithm_name == "UnknownFuture"
        assert samples[0].local_hashrate_hs == 27_400_000
        MinerSampleRepository(session).create(samples[0])
        reloaded = MinerSampleRepository(session).get_latest_by_session(record.session_id)
        assert reloaded is not None
        assert reloaded.raw_algorithm_name == "UnknownFuture"


def test_hardware_persistence_carries_session_miner_algorithm_context(temp_db):
    record = SessionManager().create_session(gpu_ids=[0])
    with temp_db.get_session() as session:
        SessionRepository(session).create(record)
        sample = HardwareSample(
            timestamp=datetime.now(),
            session_id=record.session_id,
            gpu_id=0,
            miner="srbminer",
            algorithm_ids=["pearlpow"],
            temperature_c=55.0,
        )
        repo = HardwareSampleRepository(session)
        repo.create(sample)
        stored = repo.get_latest_by_session(record.session_id)
        assert stored is not None
        assert stored.miner == "srbminer"
        assert stored.algorithm_ids == ["pearlpow"]


def test_event_persistence(temp_db):
    with temp_db.get_session() as session:
        repo = EventRepository(session)
        repo.create(Event(
            timestamp=datetime.now(),
            event_type=EventType.MINER_API_ERROR,
            source="test",
            message="safe failure",
        ))
        events = repo.get_recent()
        assert events[0].message == "safe failure"


def test_database_close_allows_file_delete(temp_db_path: Path):
    database = Database(f"sqlite:///{temp_db_path.as_posix()}")
    with database.get_session() as session:
        AlgorithmRegistry(session)
    database.close()
    assert temp_db_path.exists()
    os.remove(temp_db_path)
    assert not temp_db_path.exists()


def test_hardware_collector_safe_when_nvml_unavailable():
    collector = HardwareCollector(FakeNVMLClient(available=False))
    assert asyncio.run(collector.collect("session")) is None


def test_payout_coin_does_not_infer_algorithm():
    manager = SessionManager()
    session = manager.create_session(gpu_ids=[0], payout_coin="DOGE")
    assert session.algorithm_ids == []
    assert session.payout_coin == "DOGE"
