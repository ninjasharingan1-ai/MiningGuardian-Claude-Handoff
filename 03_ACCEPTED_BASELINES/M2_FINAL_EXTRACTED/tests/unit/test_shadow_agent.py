from datetime import datetime, timedelta
from pathlib import Path

import pytest

from mining_guardian.agent.context import ContextBuilder, WorkingMemoryBuilder, WorldStateBuilder
from mining_guardian.agent.gateway import FakeModelGateway
from mining_guardian.agent.models import AgentWorkingMemory, ExecutionStatus, ProposalType
from mining_guardian.agent.shadow import ShadowMiningAgent, ShadowSessionRequiredError
from mining_guardian.core import AlgorithmRegistry
from mining_guardian.models import HardwareSample, MinerSample, SessionRecord
from mining_guardian.storage import (
    AgentDecisionRepository,
    AgentEpisodeRepository,
    AgentLessonRepository,
    HardwareSampleRepository,
    MinerSampleRepository,
    SessionRepository,
)


def _seed_shadow_session(temp_db) -> tuple[str, datetime]:
    started = datetime(2026, 9, 16, 2, 0, 0)
    record = SessionRecord(
        session_id="session_shadow",
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
                    local_hashrate_hs=32_000_000_000_000,
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
                    utilization_gpu=97,
                    power_w=35,
                )
            )
    return record.session_id, started


def test_fake_gateway_is_deterministic_and_network_free(temp_db):
    session_id, started = _seed_shadow_session(temp_db)
    with temp_db.get_session() as session:
        world = WorldStateBuilder(
            SessionRepository(session),
            MinerSampleRepository(session),
            HardwareSampleRepository(session),
        )
        context = ContextBuilder(
            SessionRepository(session),
            MinerSampleRepository(session),
            HardwareSampleRepository(session),
        )
        builder = WorkingMemoryBuilder(
            world,
            context,
            AgentDecisionRepository(session),
            AgentLessonRepository(session),
        )
        memory = builder.build(session_id, now=started + timedelta(minutes=2))
        gateway = FakeModelGateway()
        first = gateway.reason(memory)
        second = gateway.reason(memory)
        assert first == second
        assert first.proposal.proposal_type is ProposalType.NO_ACTION
        assert gateway.provider_name == "fake"


def test_shadow_agent_persists_reasoning_but_never_executes(temp_db):
    session_id, started = _seed_shadow_session(temp_db)
    with temp_db.get_session() as session:
        session_repo = SessionRepository(session)
        miner_repo = MinerSampleRepository(session)
        hardware_repo = HardwareSampleRepository(session)
        decision_repo = AgentDecisionRepository(session)
        episode_repo = AgentEpisodeRepository(session)
        memory_builder = WorkingMemoryBuilder(
            WorldStateBuilder(session_repo, miner_repo, hardware_repo),
            ContextBuilder(session_repo, miner_repo, hardware_repo),
            decision_repo,
            AgentLessonRepository(session),
        )
        agent = ShadowMiningAgent(
            memory_builder,
            FakeModelGateway(),
            decision_repo,
            episode_repo,
        )
        result = agent.run_once(
            session_id,
            now=started + timedelta(minutes=2),
        )
        assert result.decision.proposal.proposal_type is ProposalType.NO_ACTION
        assert result.decision.execution_status is ExecutionStatus.NOT_EXECUTED_SHADOW
        assert decision_repo.get(result.decision.decision_id) is not None
        episodes = episode_repo.get_recent(session_id=session_id)
        assert episodes[0].decision_id == result.decision.decision_id


class _StaticWorkingMemoryBuilder(WorkingMemoryBuilder):
    """Test helper that returns one prebuilt typed working-memory snapshot."""

    def __init__(self, working_memory: AgentWorkingMemory) -> None:
        self.working_memory = working_memory

    def build(
        self,
        session_id: str | None = None,
        *,
        now: datetime | None = None,
    ) -> AgentWorkingMemory:
        return self.working_memory


def test_shadow_agent_requires_real_persisted_session_id(temp_db):
    session_id, started = _seed_shadow_session(temp_db)
    with temp_db.get_session() as session:
        session_repo = SessionRepository(session)
        miner_repo = MinerSampleRepository(session)
        hardware_repo = HardwareSampleRepository(session)
        decision_repo = AgentDecisionRepository(session)
        episode_repo = AgentEpisodeRepository(session)
        memory = WorkingMemoryBuilder(
            WorldStateBuilder(session_repo, miner_repo, hardware_repo),
            ContextBuilder(session_repo, miner_repo, hardware_repo),
            decision_repo,
            AgentLessonRepository(session),
        ).build(session_id, now=started + timedelta(minutes=2))
        memory.world_state.facts.session_id = None

        agent = ShadowMiningAgent(
            _StaticWorkingMemoryBuilder(memory),
            FakeModelGateway(),
            decision_repo,
            episode_repo,
        )

        with pytest.raises(ShadowSessionRequiredError):
            agent.run_once(now=started + timedelta(minutes=2))

        assert decision_repo.get_recent(session_id=session_id) == []
        assert episode_repo.get_recent(session_id=session_id) == []


def test_shadow_episode_omits_missing_canonical_algorithm_ids(temp_db):
    session_id, started = _seed_shadow_session(temp_db)
    with temp_db.get_session() as session:
        session_repo = SessionRepository(session)
        miner_repo = MinerSampleRepository(session)
        hardware_repo = HardwareSampleRepository(session)
        decision_repo = AgentDecisionRepository(session)
        episode_repo = AgentEpisodeRepository(session)
        memory = WorkingMemoryBuilder(
            WorldStateBuilder(session_repo, miner_repo, hardware_repo),
            ContextBuilder(session_repo, miner_repo, hardware_repo),
            decision_repo,
            AgentLessonRepository(session),
        ).build(session_id, now=started + timedelta(minutes=2))
        workload = memory.world_state.facts.workloads[0]
        workload.canonical_algorithm_id = None
        workload.canonical_algorithm_name = None

        agent = ShadowMiningAgent(
            _StaticWorkingMemoryBuilder(memory),
            FakeModelGateway(),
            decision_repo,
            episode_repo,
        )
        result = agent.run_once(now=started + timedelta(minutes=2))

        assert result.episode.algorithm_ids == []
        assert result.working_memory.world_state.facts.workloads[0].raw_algorithm_name == "pearlhash"


def test_agent_package_has_no_hardware_miner_network_or_process_control_dependencies():
    source_root = Path(__file__).resolve().parents[2] / "src" / "mining_guardian" / "agent"
    combined = "\n".join(path.read_text(encoding="utf-8") for path in source_root.rglob("*.py"))
    forbidden = (
        "mining_guardian.adapters",
        "..adapters",
        "pynvml",
        "httpx",
        "requests",
        "openai",
        "anthropic",
        "subprocess",
        "os.system",
        "nvmlDeviceSet",
        "restart(",
        "kill(",
        "terminate(",
    )
    for token in forbidden:
        assert token not in combined
