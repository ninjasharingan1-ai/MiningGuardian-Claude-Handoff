"""SQLite repositories for M2.1 cognitive records."""

import json

from sqlalchemy.orm import Session

from ..agent.models import (
    AgentDecision,
    AgentEpisode,
    AgentHypothesis,
    AgentLesson,
    AgentProposal,
    AgentWorkingMemory,
    ExecutionStatus,
    LessonScope,
    ValidatorStatus,
)
from .schema import AgentDecisionDB, AgentEpisodeDB, AgentLessonDB


class AgentEpisodeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, episode: AgentEpisode) -> AgentEpisode:
        self.session.add(
            AgentEpisodeDB(
                episode_id=episode.episode_id,
                timestamp=episode.timestamp,
                session_id=episode.session_id,
                episode_type=episode.episode_type.value,
                algorithm_ids_json=json.dumps(episode.algorithm_ids),
                summary=episode.summary,
                world_state_timestamp=episode.world_state_timestamp,
                decision_id=episode.decision_id,
                episode_metadata_json=json.dumps(episode.metadata, default=str),
            )
        )
        self.session.commit()
        return episode

    def get_recent(
        self,
        *,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[AgentEpisode]:
        query = self.session.query(AgentEpisodeDB)
        if session_id is not None:
            query = query.filter_by(session_id=session_id)
        rows = query.order_by(AgentEpisodeDB.timestamp.desc()).limit(limit).all()
        return [self._to_model(row) for row in rows]

    @staticmethod
    def _to_model(row: AgentEpisodeDB) -> AgentEpisode:
        from ..agent.models import EpisodeType

        return AgentEpisode(
            episode_id=row.episode_id,
            timestamp=row.timestamp,
            session_id=row.session_id,
            episode_type=EpisodeType(row.episode_type),
            algorithm_ids=json.loads(row.algorithm_ids_json or "[]"),
            summary=row.summary,
            world_state_timestamp=row.world_state_timestamp,
            decision_id=row.decision_id,
            metadata=json.loads(row.episode_metadata_json or "{}"),
        )


class AgentDecisionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, decision: AgentDecision) -> AgentDecision:
        self.session.add(
            AgentDecisionDB(
                decision_id=decision.decision_id,
                timestamp=decision.timestamp,
                session_id=decision.session_id,
                world_state_timestamp=decision.world_state_timestamp,
                working_memory_json=decision.working_memory.model_dump_json(),
                hypotheses_json=json.dumps(
                    [item.model_dump(mode="json") for item in decision.hypotheses]
                ),
                evidence_json=json.dumps(decision.evidence),
                missing_evidence_json=json.dumps(decision.missing_evidence),
                proposal_json=decision.proposal.model_dump_json(),
                confidence=decision.confidence,
                validator_status=decision.validator_status.value,
                execution_status=decision.execution_status.value,
                future_outcome_reference=decision.future_outcome_reference,
                lesson_reference=decision.lesson_reference,
                model_provider=decision.model_provider,
                model_name=decision.model_name,
                agent_version=decision.agent_version,
            )
        )
        self.session.commit()
        return decision

    def get(self, decision_id: str) -> AgentDecision | None:
        row = self.session.get(AgentDecisionDB, decision_id)
        return self._to_model(row) if row else None

    def get_recent(
        self,
        *,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[AgentDecision]:
        query = self.session.query(AgentDecisionDB)
        if session_id is not None:
            query = query.filter_by(session_id=session_id)
        rows = query.order_by(AgentDecisionDB.timestamp.desc()).limit(limit).all()
        return [self._to_model(row) for row in rows]

    @staticmethod
    def _to_model(row: AgentDecisionDB) -> AgentDecision:
        return AgentDecision(
            decision_id=row.decision_id,
            timestamp=row.timestamp,
            session_id=row.session_id,
            world_state_timestamp=row.world_state_timestamp,
            working_memory=AgentWorkingMemory.model_validate_json(row.working_memory_json),
            hypotheses=[
                AgentHypothesis.model_validate(item)
                for item in json.loads(row.hypotheses_json or "[]")
            ],
            evidence=json.loads(row.evidence_json or "[]"),
            missing_evidence=json.loads(row.missing_evidence_json or "[]"),
            proposal=AgentProposal.model_validate_json(row.proposal_json),
            confidence=row.confidence,
            validator_status=ValidatorStatus(row.validator_status),
            execution_status=ExecutionStatus(row.execution_status),
            future_outcome_reference=row.future_outcome_reference,
            lesson_reference=row.lesson_reference,
            model_provider=row.model_provider,
            model_name=row.model_name,
            agent_version=row.agent_version,
        )


class AgentLessonRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, lesson: AgentLesson) -> AgentLesson:
        self.session.add(
            AgentLessonDB(
                lesson_id=lesson.lesson_id,
                timestamp=lesson.timestamp,
                session_id=lesson.scope.session_id,
                claim=lesson.claim,
                supporting_observations_json=json.dumps(lesson.supporting_observations),
                confidence=lesson.confidence,
                scope_json=lesson.scope.model_dump_json(),
                algorithm_id=lesson.algorithm_id,
                hardware_identity_json=json.dumps(lesson.hardware_identity, default=str),
                supersedes_lesson_id=lesson.supersedes_lesson_id,
                superseded_by_lesson_id=lesson.superseded_by_lesson_id,
            )
        )
        self.session.commit()
        return lesson

    def get(self, lesson_id: str) -> AgentLesson | None:
        row = self.session.get(AgentLessonDB, lesson_id)
        return self._to_model(row) if row else None

    def get_recent(self, *, limit: int = 20) -> list[AgentLesson]:
        rows = (
            self.session.query(AgentLessonDB)
            .order_by(AgentLessonDB.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [self._to_model(row) for row in rows]

    def get_relevant(
        self,
        *,
        session_id: str,
        algorithm_ids: set[str],
        limit: int = 5,
    ) -> list[AgentLesson]:
        candidates = self.get_recent(limit=max(50, limit))
        relevant: list[AgentLesson] = []
        for lesson in candidates:
            same_session = lesson.scope.session_id == session_id
            same_algorithm = (
                lesson.algorithm_id is not None and lesson.algorithm_id in algorithm_ids
            )
            global_lesson = lesson.scope.session_id is None and lesson.algorithm_id is None
            if same_session or same_algorithm or global_lesson:
                relevant.append(lesson)
            if len(relevant) >= limit:
                break
        return relevant

    @staticmethod
    def _to_model(row: AgentLessonDB) -> AgentLesson:
        return AgentLesson(
            lesson_id=row.lesson_id,
            timestamp=row.timestamp,
            claim=row.claim,
            supporting_observations=json.loads(row.supporting_observations_json or "[]"),
            confidence=row.confidence,
            scope=LessonScope.model_validate_json(row.scope_json),
            algorithm_id=row.algorithm_id,
            hardware_identity=json.loads(row.hardware_identity_json or "{}"),
            supersedes_lesson_id=row.supersedes_lesson_id,
            superseded_by_lesson_id=row.superseded_by_lesson_id,
        )
