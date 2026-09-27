from datetime import datetime

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from mining_guardian.agent.models import (
    AgentDecision,
    AgentEpisode,
    AgentLesson,
    AgentProposal,
    AgentWorkingMemory,
    DerivedWorldMetrics,
    EpisodeType,
    ExecutionStatus,
    LessonScope,
    MeasuredWorldFacts,
    MiningWorldState,
    ProposalType,
    ValidatorStatus,
)
from mining_guardian.core import AlgorithmRegistry
from mining_guardian.models import SessionRecord
from mining_guardian.storage import (
    AgentDecisionRepository,
    AgentEpisodeRepository,
    AgentLessonRepository,
    Database,
    SessionRepository,
)
from mining_guardian.storage.schema import (
    AlgorithmAliasDB,
    AlgorithmDB,
    Base,
    EventDB,
    HardwareSampleDB,
    MinerSampleDB,
    SessionDB,
)


def _working_memory(session_id: str) -> AgentWorkingMemory:
    now = datetime(2026, 9, 16, 0, 0, 0)
    return AgentWorkingMemory(
        world_state=MiningWorldState(
            timestamp=now,
            facts=MeasuredWorldFacts(
                session_id=session_id,
                session_start_time=now,
                miner="srbminer",
            ),
            derived=DerivedWorldMetrics(session_age_seconds=0),
            missing_signals=["workloads", "gpu_telemetry"],
        )
    )


def test_episode_decision_and_lesson_persist(temp_db):
    now = datetime(2026, 9, 16, 0, 0, 0)
    session_record = SessionRecord(
        session_id="session_agent_persistence",
        start_time=now,
        algorithm_ids=["pearlpow"],
    )
    with temp_db.get_session() as session:
        AlgorithmRegistry(session)
        SessionRepository(session).create(session_record)

        lesson = AgentLesson(
            lesson_id="lesson_1",
            timestamp=now,
            claim="Session-scoped observation only.",
            supporting_observations=["observation_1"],
            confidence=0.5,
            scope=LessonScope(
                session_id=session_record.session_id,
                algorithm_id="pearlpow",
                miner="srbminer",
                gpu_ids=[0],
            ),
            algorithm_id="pearlpow",
        )
        AgentLessonRepository(session).create(lesson)

        memory = _working_memory(session_record.session_id)
        decision = AgentDecision(
            decision_id="decision_1",
            timestamp=now,
            session_id=session_record.session_id,
            world_state_timestamp=now,
            working_memory=memory,
            evidence=["persisted telemetry"],
            missing_evidence=["longer window"],
            proposal=AgentProposal(
                proposal_type=ProposalType.NO_ACTION,
                rationale="Shadow mode.",
                confidence=1.0,
            ),
            confidence=1.0,
            validator_status=ValidatorStatus.VALIDATED,
            execution_status=ExecutionStatus.NOT_EXECUTED_SHADOW,
            model_provider="fake",
            model_name="deterministic-m2.1",
            agent_version="m2.1",
        )
        AgentDecisionRepository(session).create(decision)

        episode = AgentEpisode(
            episode_id="episode_1",
            timestamp=now,
            session_id=session_record.session_id,
            episode_type=EpisodeType.SHADOW_REASONING_CYCLE,
            algorithm_ids=["pearlpow"],
            summary="Shadow cycle recorded.",
            world_state_timestamp=now,
            decision_id=decision.decision_id,
        )
        AgentEpisodeRepository(session).create(episode)

        stored_decision = AgentDecisionRepository(session).get("decision_1")
        stored_lesson = AgentLessonRepository(session).get("lesson_1")
        stored_episode = AgentEpisodeRepository(session).get_recent(
            session_id=session_record.session_id,
            limit=1,
        )[0]

        assert stored_decision is not None
        assert stored_decision.proposal.proposal_type is ProposalType.NO_ACTION
        assert stored_decision.execution_status is ExecutionStatus.NOT_EXECUTED_SHADOW
        assert stored_decision.working_memory.world_state.facts.session_id == session_record.session_id
        assert stored_lesson is not None
        assert stored_lesson.scope.algorithm_id == "pearlpow"
        assert stored_episode.decision_id == "decision_1"


def test_m21_schema_adds_only_new_agent_tables_to_existing_m1_database(tmp_path):
    database_path = tmp_path / "legacy_m1.db"
    url = f"sqlite:///{database_path.as_posix()}"
    engine = create_engine(url)
    m1_tables = [
        AlgorithmDB.__table__,
        AlgorithmAliasDB.__table__,
        SessionDB.__table__,
        HardwareSampleDB.__table__,
        MinerSampleDB.__table__,
        EventDB.__table__,
    ]
    Base.metadata.create_all(engine, tables=m1_tables)

    with Session(engine) as session:
        session.add(
            SessionDB(
                session_id="legacy_session",
                miner="srbminer",
                gpu_ids_json="[0]",
                algorithm_ids_json="[]",
                raw_algorithm_names_json="[]",
                payout_coin=None,
                start_time=datetime(2026, 9, 15, 23, 0, 0),
                end_time=None,
                state="observe",
                health="healthy",
            )
        )
        session.commit()
    engine.dispose()

    database = Database(url)
    try:
        table_names = set(inspect(database.engine).get_table_names())
        assert {"agent_episodes", "agent_decisions", "agent_lessons"} <= table_names
        with database.get_session() as session:
            legacy = SessionRepository(session).get_by_id("legacy_session")
            assert legacy is not None
            assert legacy.miner == "srbminer"
    finally:
        database.close()



def test_lesson_supersession_fields_round_trip(temp_db):
    now = datetime(2026, 9, 16, 3, 0, 0)
    with temp_db.get_session() as session:
        first = AgentLesson(
            lesson_id="lesson_old",
            timestamp=now,
            claim="Earlier bounded observation.",
            confidence=0.4,
            superseded_by_lesson_id="lesson_new",
        )
        second = AgentLesson(
            lesson_id="lesson_new",
            timestamp=now,
            claim="Revised bounded observation.",
            confidence=0.6,
            supersedes_lesson_id="lesson_old",
        )
        repo = AgentLessonRepository(session)
        repo.create(first)
        repo.create(second)
        assert repo.get("lesson_old").superseded_by_lesson_id == "lesson_new"
        assert repo.get("lesson_new").supersedes_lesson_id == "lesson_old"
