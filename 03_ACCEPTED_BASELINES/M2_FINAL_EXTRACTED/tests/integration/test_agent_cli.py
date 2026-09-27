from datetime import datetime, timedelta

from click.testing import CliRunner

from mining_guardian.cli.commands import cli
from mining_guardian.core import AlgorithmRegistry
from mining_guardian.models import HardwareSample, MinerSample, SessionRecord
from mining_guardian.storage import (
    AgentDecisionRepository,
    Database,
    HardwareSampleRepository,
    MinerSampleRepository,
    SessionRepository,
)


def _seed_cli_database(path) -> None:
    database = Database(f"sqlite:///{path.as_posix()}")
    started = datetime.now() - timedelta(minutes=2)
    try:
        with database.get_session() as session:
            AlgorithmRegistry(session)
            record = SessionRecord(
                session_id="session_cli_agent",
                miner="srbminer",
                gpu_ids=[0],
                algorithm_ids=["pearlpow"],
                raw_algorithm_names=["pearlhash"],
                start_time=started,
            )
            SessionRepository(session).create(record)
            miner_repo = MinerSampleRepository(session)
            hardware_repo = HardwareSampleRepository(session)
            for index in range(2):
                timestamp = started + timedelta(seconds=index * 60)
                miner_repo.create(
                    MinerSample(
                        timestamp=timestamp,
                        session_id=record.session_id,
                        miner="srbminer",
                        raw_algorithm_name="pearlhash",
                        canonical_algorithm_id="pearlpow",
                        canonical_algorithm_name="PearlPow",
                        local_hashrate_hs=32_459_610_144_862.57,
                        accepted_shares=index,
                        rejected_shares=0,
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
                        temperature_c=61,
                        utilization_gpu=96,
                        power_w=35,
                    )
                )
    finally:
        database.close()


def test_agent_context_cli_is_read_only_and_human_readable(tmp_path):
    database_path = tmp_path / "agent_cli.db"
    _seed_cli_database(database_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["agent-context"],
        env={"DATABASE_PATH": str(database_path)},
    )

    assert result.exit_code == 0, result.output
    assert "AGENT CONTEXT - READ ONLY" in result.output
    assert "PearlPow" in result.output
    assert "pearlhash" in result.output
    assert "32.46 TH/s" in result.output
    assert "Context windows:" in result.output

    database = Database(f"sqlite:///{database_path.as_posix()}")
    try:
        with database.get_session() as session:
            assert AgentDecisionRepository(session).get_recent() == []
    finally:
        database.close()


def test_agent_shadow_once_cli_persists_no_action_decision(tmp_path):
    database_path = tmp_path / "agent_shadow.db"
    _seed_cli_database(database_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["agent-shadow-once"],
        env={"DATABASE_PATH": str(database_path)},
    )

    assert result.exit_code == 0, result.output
    assert "SHADOW MODE" in result.output
    assert "NO ACTION WILL BE EXECUTED" in result.output
    assert "Proposal: no_action" in result.output
    assert "Execution: not_executed_shadow" in result.output

    database = Database(f"sqlite:///{database_path.as_posix()}")
    try:
        with database.get_session() as session:
            decisions = AgentDecisionRepository(session).get_recent()
            assert len(decisions) == 1
            assert decisions[0].proposal.proposal_type.value == "no_action"
    finally:
        database.close()


def test_agent_context_cli_marks_ended_persisted_session_historical(tmp_path):
    database_path = tmp_path / "agent_cli_ended.db"
    _seed_cli_database(database_path)
    database = Database(f"sqlite:///{database_path.as_posix()}")
    try:
        with database.get_session() as session:
            latest = SessionRepository(session).get_latest()
            assert latest is not None
            SessionRepository(session).update_end_time(
                latest.session_id,
                latest.start_time + timedelta(seconds=61),
            )
    finally:
        database.close()

    result = CliRunner().invoke(
        cli,
        ["agent-context"],
        env={"DATABASE_PATH": str(database_path)},
    )

    assert result.exit_code == 0, result.output
    assert "Observation origin: persisted" in result.output
    assert "Guardian session: ended" in result.output
    assert "Session duration: 61 seconds" in result.output
    assert "Session age:" not in result.output


def test_agent_context_live_is_ephemeral_and_read_only(tmp_path, monkeypatch):
    from mining_guardian.cli import commands
    from tests.fixtures.fakes import FakeNVMLClient, FakeSRBMinerClient

    database_path = tmp_path / "agent_cli_live.db"
    _seed_cli_database(database_path)
    database = Database(f"sqlite:///{database_path.as_posix()}")
    try:
        with database.get_session() as session:
            latest = SessionRepository(session).get_latest()
            assert latest is not None
            SessionRepository(session).update_end_time(
                latest.session_id,
                latest.start_time + timedelta(seconds=61),
            )
    finally:
        database.close()

    class LiveMiner(FakeSRBMinerClient):
        async def snapshot(self):
            snapshot = await super().snapshot()
            assert snapshot is not None
            snapshot.miner_version = "3.6.4"
            snapshot.workloads[0].device_ids = [1]
            return snapshot

    monkeypatch.setattr(commands, "SRBMinerClient", lambda **_kwargs: LiveMiner())
    monkeypatch.setattr(commands, "NVMLClient", lambda: FakeNVMLClient())

    before_database = Database(f"sqlite:///{database_path.as_posix()}")
    try:
        with before_database.get_session() as session:
            from mining_guardian.storage.schema import HardwareSampleDB, MinerSampleDB, SessionDB

            session_count_before = session.query(SessionDB).count()
            miner_count_before = session.query(MinerSampleDB).count()
            hardware_count_before = session.query(HardwareSampleDB).count()
    finally:
        before_database.close()

    result = CliRunner().invoke(
        cli,
        ["agent-context", "--live"],
        env={"DATABASE_PATH": str(database_path)},
    )

    assert result.exit_code == 0, result.output
    assert "AGENT CONTEXT - READ ONLY" in result.output
    assert "Observation origin: live_probe" in result.output
    assert "Freshness: fresh" in result.output
    assert "Guardian session: ended" in result.output
    assert "Miner version: 3.6.4" in result.output
    assert "PearlPow" in result.output
    assert "Historical context:" in result.output
    assert "source: persisted" in result.output

    after_database = Database(f"sqlite:///{database_path.as_posix()}")
    try:
        with after_database.get_session() as session:
            from mining_guardian.storage.schema import HardwareSampleDB, MinerSampleDB, SessionDB

            assert session.query(SessionDB).count() == session_count_before
            assert session.query(MinerSampleDB).count() == miner_count_before
            assert session.query(HardwareSampleDB).count() == hardware_count_before
    finally:
        after_database.close()
