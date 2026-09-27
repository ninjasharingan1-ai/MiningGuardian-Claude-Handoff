"""Atomic persistence for already-produced M2.2.2 decision artifacts."""

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..agent.decision.confidence import (
    ConfidenceLimitation,
    DecisionConfidenceResult,
    EvidenceConfidenceInput,
)
from ..agent.decision.explanation import DecisionExplanation
from ..agent.decision.models import (
    ActionType,
    CandidateAction,
    DecisionResult,
    ExecutionCategory,
)
from ..agent.decision.policies import PolicyResult
from ..agent.decision.predictors import PredictionHorizon, PredictionResult
from ..agent.decision.ranking import RankedCandidate
from ..agent.decision.scoring import DecisionScore
from ..agent.temporal import FreshnessLevel
from .schema import (
    DecisionCandidateDB,
    DecisionConfidenceDB,
    DecisionEvaluationDB,
    DecisionExplanationDB,
    DecisionPolicyResultDB,
    DecisionPredictionDB,
    DecisionRankingDB,
    DecisionScoreDB,
)


class DecisionPersistenceIntegrityError(ValueError):
    """Raised when supplied decision artifacts form an inconsistent graph."""


def _serialize_timestamp(value: datetime) -> str:
    """Preserve the supplied timestamp without timezone normalization."""

    return value.isoformat(timespec="microseconds")


_POLICY_VIOLATIONS = TypeAdapter(list[str])
_EVIDENCE_INPUTS = TypeAdapter(list[EvidenceConfidenceInput])
_CONFIDENCE_LIMITATIONS = TypeAdapter(list[ConfidenceLimitation])


def _deserialize_timestamp(value: str) -> datetime:
    """Restore the authoritative timestamp representation without normalization."""

    return datetime.fromisoformat(value)


class DecisionEvaluationArtifacts(BaseModel):
    """Immutable handoff of already-produced decision artifacts to persistence."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    session_id: str | None = None
    result: DecisionResult
    candidates: tuple[CandidateAction, ...]
    policy_results: dict[str, PolicyResult] = Field(default_factory=dict)
    predictions: dict[str, PredictionResult] = Field(default_factory=dict)
    scores: dict[str, DecisionScore] = Field(default_factory=dict)
    ranking: tuple[RankedCandidate, ...] = ()
    confidence: DecisionConfidenceResult | None = None
    explanation: DecisionExplanation | None = None


class DecisionEvaluationRepository:
    """Persist one complete decision-evaluation graph atomically."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, artifacts: DecisionEvaluationArtifacts) -> DecisionEvaluationDB:
        """Persist one artifact graph from a Session with no pending ORM changes."""

        self._require_clean_session()

        try:
            membership = self._validate_artifacts(artifacts)
            self._ensure_new_decision_id(artifacts.result.decision_id)

            explanation_json = (
                artifacts.explanation.model_dump_json()
                if artifacts.explanation is not None
                else None
            )
            evaluation = DecisionEvaluationDB(
                decision_id=artifacts.result.decision_id,
                timestamp=artifacts.timestamp,
                timestamp_iso=_serialize_timestamp(artifacts.timestamp),
                session_id=artifacts.session_id,
                state=artifacts.result.state,
                selected_candidate_id=None,
                confidence=artifacts.result.confidence,
                result_explanation=artifacts.result.explanation,
                explanation_json=explanation_json,
            )
            self.session.add(evaluation)
            self.session.flush()

            candidate_rows = self._persist_candidates(
                evaluation=evaluation,
                candidates=artifacts.candidates,
                membership=membership,
            )
            self.session.flush()

            selected = artifacts.result.selected_action
            if selected is not None:
                selected_row = candidate_rows[selected.id]
                self._require_owned_candidate(evaluation, selected_row, "selected")
                evaluation.selected_candidate_id = selected_row.id

            self._persist_policy_results(
                artifacts.policy_results,
                candidate_rows,
            )
            self._persist_predictions(
                artifacts.predictions,
                candidate_rows,
            )
            self._persist_scores(
                artifacts.scores,
                candidate_rows,
            )
            ranking_rows = self._persist_rankings(
                evaluation,
                artifacts.ranking,
                candidate_rows,
            )
            confidence_row = self._persist_confidence(
                evaluation,
                artifacts.confidence,
                candidate_rows,
            )
            self._persist_explanation(evaluation, explanation_json)

            self.session.flush()
            self._validate_persisted_ownership(
                evaluation=evaluation,
                candidate_rows=candidate_rows,
                ranking_rows=ranking_rows,
                confidence_row=confidence_row,
            )
            self.session.commit()
            return evaluation
        except Exception:
            self.session.rollback()
            raise

    def _require_clean_session(self) -> None:
        """Require repository-owned writes to start from a clean pending-state Session."""

        if self.session.new or self.session.dirty or self.session.deleted:
            raise DecisionPersistenceIntegrityError(
                "DecisionEvaluationRepository.save() requires a clean/dedicated "
                "Session with no pending new, dirty, or deleted ORM state"
            )

    def get_by_decision_id(self, decision_id: str) -> DecisionEvaluationDB | None:
        """Return the stored ORM graph without reconstructing decision semantics."""

        statement = (
            select(DecisionEvaluationDB)
            .where(DecisionEvaluationDB.decision_id == decision_id)
            .options(
                selectinload(DecisionEvaluationDB.selected_candidate),
                selectinload(DecisionEvaluationDB.rankings),
                selectinload(DecisionEvaluationDB.confidence_artifact),
                selectinload(DecisionEvaluationDB.explanation),
                selectinload(DecisionEvaluationDB.candidates).selectinload(
                    DecisionCandidateDB.policy_result
                ),
                selectinload(DecisionEvaluationDB.candidates).selectinload(
                    DecisionCandidateDB.prediction
                ),
                selectinload(DecisionEvaluationDB.candidates).selectinload(
                    DecisionCandidateDB.score
                ),
                selectinload(DecisionEvaluationDB.candidates).selectinload(
                    DecisionCandidateDB.ranking
                ),
            )
        )
        return self.session.execute(statement).scalar_one_or_none()

    def load_artifacts(
        self,
        decision_id: str,
    ) -> DecisionEvaluationArtifacts | None:
        """Reconstruct persisted domain artifacts without recomputation or writes."""

        with self.session.no_autoflush:
            evaluation = self.get_by_decision_id(decision_id)
            if evaluation is None:
                return None
            try:
                return self._artifacts_from_evaluation(evaluation)
            except DecisionPersistenceIntegrityError:
                raise
            except (TypeError, ValueError) as exc:
                raise DecisionPersistenceIntegrityError(
                    f"persisted decision evaluation is invalid: {decision_id}"
                ) from exc

    def _artifacts_from_evaluation(
        self,
        evaluation: DecisionEvaluationDB,
    ) -> DecisionEvaluationArtifacts:
        candidate_rows_by_id: dict[int, DecisionCandidateDB] = {}
        candidates_by_row_id: dict[int, CandidateAction] = {}
        domain_ids: set[str] = set()

        for candidate_row in evaluation.candidates:
            if candidate_row.decision_evaluation_id != evaluation.id:
                raise DecisionPersistenceIntegrityError(
                    "candidate row belongs to another decision evaluation"
                )
            if candidate_row.id in candidate_rows_by_id:
                raise DecisionPersistenceIntegrityError(
                    "duplicate persisted candidate row identity"
                )
            if candidate_row.candidate_id in domain_ids:
                raise DecisionPersistenceIntegrityError(
                    f"duplicate candidate domain id: {candidate_row.candidate_id}"
                )
            candidate_rows_by_id[candidate_row.id] = candidate_row
            candidates_by_row_id[candidate_row.id] = self._candidate_from_row(
                candidate_row
            )
            domain_ids.add(candidate_row.candidate_id)

        selected_row, alternative_rows, rejected_rows = self._membership_rows(
            evaluation,
            candidate_rows_by_id,
        )
        selected_action = (
            candidates_by_row_id[selected_row.id]
            if selected_row is not None
            else None
        )
        alternatives = [
            candidates_by_row_id[candidate_row.id]
            for candidate_row in alternative_rows
        ]
        rejected_alternatives = [
            candidates_by_row_id[candidate_row.id]
            for candidate_row in rejected_rows
        ]

        canonical_candidate_rows = [
            *([selected_row] if selected_row is not None else []),
            *alternative_rows,
            *rejected_rows,
        ]
        canonical_candidates = tuple(
            candidates_by_row_id[candidate_row.id]
            for candidate_row in canonical_candidate_rows
        )

        policy_results: dict[str, PolicyResult] = {}
        predictions: dict[str, PredictionResult] = {}
        scores: dict[str, DecisionScore] = {}

        for candidate_row in evaluation.candidates:
            candidate_id = candidate_row.candidate_id
            if candidate_row.policy_result is not None:
                policy_row = candidate_row.policy_result
                if policy_row.candidate_id != candidate_row.id:
                    raise DecisionPersistenceIntegrityError(
                        "policy result references a different candidate row"
                    )
                policy_results[candidate_id] = self._policy_from_row(policy_row)
            if candidate_row.prediction is not None:
                prediction_row = candidate_row.prediction
                if prediction_row.candidate_id != candidate_row.id:
                    raise DecisionPersistenceIntegrityError(
                        "prediction references a different candidate row"
                    )
                predictions[candidate_id] = self._prediction_from_row(
                    prediction_row,
                    candidate_id,
                )
            if candidate_row.score is not None:
                score_row = candidate_row.score
                if score_row.candidate_id != candidate_row.id:
                    raise DecisionPersistenceIntegrityError(
                        "score references a different candidate row"
                    )
                scores[candidate_id] = self._score_from_row(
                    score_row,
                    candidate_id,
                )

        ranking = self._ranking_from_rows(
            evaluation,
            candidates_by_row_id,
            scores,
        )
        confidence = self._confidence_from_evaluation(
            evaluation,
            candidates_by_row_id,
        )
        explanation = self._explanation_from_evaluation(evaluation)

        if evaluation.confidence is None:
            raise DecisionPersistenceIntegrityError(
                "persisted DecisionResult.confidence is missing"
            )

        result = DecisionResult(
            decision_id=evaluation.decision_id,
            state=evaluation.state,
            selected_action=selected_action,
            alternatives=alternatives,
            rejected_alternatives=rejected_alternatives,
            confidence=evaluation.confidence,
            explanation=evaluation.result_explanation,
        )

        return DecisionEvaluationArtifacts(
            timestamp=_deserialize_timestamp(evaluation.timestamp_iso),
            session_id=evaluation.session_id,
            result=result,
            candidates=canonical_candidates,
            policy_results=policy_results,
            predictions=predictions,
            scores=scores,
            ranking=ranking,
            confidence=confidence,
            explanation=explanation,
        )

    @staticmethod
    def _candidate_from_row(candidate_row: DecisionCandidateDB) -> CandidateAction:
        return CandidateAction(
            id=candidate_row.candidate_id,
            action_type=ActionType(candidate_row.action_type),
            description=candidate_row.description,
            execution_category=ExecutionCategory(
                candidate_row.execution_category
            ),
            expected_gain=candidate_row.expected_gain,
            confidence=candidate_row.confidence,
            risk_score=candidate_row.risk_score,
            transition_cost=candidate_row.transition_cost,
            reversible=candidate_row.reversible,
        )

    @classmethod
    def _membership_rows(
        cls,
        evaluation: DecisionEvaluationDB,
        candidate_rows_by_id: dict[int, DecisionCandidateDB],
    ) -> tuple[
        DecisionCandidateDB | None,
        list[DecisionCandidateDB],
        list[DecisionCandidateDB],
    ]:
        selected_rows: list[DecisionCandidateDB] = []
        alternative_rows: list[DecisionCandidateDB] = []
        rejected_rows: list[DecisionCandidateDB] = []

        for candidate_row in candidate_rows_by_id.values():
            role = candidate_row.result_role
            position = candidate_row.result_position
            if role == "selected":
                if position is not None:
                    raise DecisionPersistenceIntegrityError(
                        "selected candidate must have NULL result_position"
                    )
                selected_rows.append(candidate_row)
            elif role == "alternative":
                cls._require_result_position(candidate_row)
                alternative_rows.append(candidate_row)
            elif role == "rejected":
                cls._require_result_position(candidate_row)
                rejected_rows.append(candidate_row)
            else:
                raise DecisionPersistenceIntegrityError(
                    f"invalid persisted candidate result_role: {role}"
                )

        if len(selected_rows) > 1:
            raise DecisionPersistenceIntegrityError(
                "multiple selected candidate memberships are persisted"
            )

        selected_row = selected_rows[0] if selected_rows else None
        if evaluation.selected_candidate_id is None:
            if selected_row is not None:
                raise DecisionPersistenceIntegrityError(
                    "selected membership exists without selected_candidate_id"
                )
        else:
            owned_selected = candidate_rows_by_id.get(
                evaluation.selected_candidate_id
            )
            if owned_selected is None:
                raise DecisionPersistenceIntegrityError(
                    "selected_candidate_id points outside this decision evaluation"
                )
            if selected_row is None or selected_row.id != owned_selected.id:
                raise DecisionPersistenceIntegrityError(
                    "selected_candidate_id disagrees with persisted selected membership"
                )

        cls._validate_result_positions(alternative_rows, "alternative")
        cls._validate_result_positions(rejected_rows, "rejected")
        alternative_rows.sort(key=cls._result_position)
        rejected_rows.sort(key=cls._result_position)
        return selected_row, alternative_rows, rejected_rows

    @staticmethod
    def _require_result_position(candidate_row: DecisionCandidateDB) -> None:
        position = candidate_row.result_position
        if position is None or position < 0:
            raise DecisionPersistenceIntegrityError(
                f"{candidate_row.result_role} candidate has invalid result_position"
            )

    @staticmethod
    def _result_position(candidate_row: DecisionCandidateDB) -> int:
        position = candidate_row.result_position
        if position is None:
            raise DecisionPersistenceIntegrityError(
                f"{candidate_row.result_role} candidate is missing result_position"
            )
        return position

    @classmethod
    def _validate_result_positions(
        cls,
        candidate_rows: list[DecisionCandidateDB],
        role: str,
    ) -> None:
        positions = sorted(cls._result_position(row) for row in candidate_rows)
        if positions != list(range(len(candidate_rows))):
            raise DecisionPersistenceIntegrityError(
                f"{role} result positions are incomplete or contradictory"
            )

    @staticmethod
    def _policy_from_row(policy_row: DecisionPolicyResultDB) -> PolicyResult:
        violations = _POLICY_VIOLATIONS.validate_json(
            policy_row.violations_json
        )
        return PolicyResult(
            allowed=policy_row.allowed,
            violations=violations,
        )

    @staticmethod
    def _prediction_from_row(
        prediction_row: DecisionPredictionDB,
        candidate_id: str,
    ) -> PredictionResult:
        return PredictionResult(
            candidate_id=candidate_id,
            expected_reward_change=prediction_row.expected_reward_change,
            expected_hashrate_change=prediction_row.expected_hashrate_change,
            expected_power_change=prediction_row.expected_power_change,
            confidence=prediction_row.confidence,
            uncertainty=prediction_row.uncertainty,
            horizon=PredictionHorizon(prediction_row.horizon),
            rationale=prediction_row.rationale,
        )

    @staticmethod
    def _score_from_row(
        score_row: DecisionScoreDB,
        candidate_id: str,
    ) -> DecisionScore:
        return DecisionScore(
            candidate_id=candidate_id,
            benefit=score_row.benefit,
            confidence=score_row.confidence,
            risk=score_row.risk,
            action_cost=score_row.action_cost,
            uncertainty=score_row.uncertainty,
            utility_score=score_row.utility_score,
        )

    @classmethod
    def _ranking_from_rows(
        cls,
        evaluation: DecisionEvaluationDB,
        candidates_by_row_id: dict[int, CandidateAction],
        scores: dict[str, DecisionScore],
    ) -> tuple[RankedCandidate, ...]:
        ranked_candidates: list[RankedCandidate] = []
        ranked_candidate_ids: set[int] = set()
        ranks: set[int] = set()

        for ranking_row in evaluation.rankings:
            if ranking_row.decision_evaluation_id != evaluation.id:
                raise DecisionPersistenceIntegrityError(
                    "ranking row belongs to another decision evaluation"
                )
            candidate = candidates_by_row_id.get(ranking_row.candidate_id)
            if candidate is None:
                raise DecisionPersistenceIntegrityError(
                    "ranking references candidate outside this decision evaluation"
                )
            if ranking_row.candidate_id in ranked_candidate_ids:
                raise DecisionPersistenceIntegrityError(
                    "duplicate ranked candidate is persisted"
                )
            if ranking_row.rank_position in ranks:
                raise DecisionPersistenceIntegrityError(
                    "duplicate ranking position is persisted"
                )
            score = scores.get(candidate.id)
            if score is None:
                raise DecisionPersistenceIntegrityError(
                    f"ranking candidate missing persisted DecisionScore: {candidate.id}"
                )
            ranked_candidates.append(
                RankedCandidate(
                    rank=ranking_row.rank_position,
                    candidate=candidate,
                    score=score,
                )
            )
            ranked_candidate_ids.add(ranking_row.candidate_id)
            ranks.add(ranking_row.rank_position)

        ranked_candidates.sort(key=lambda item: item.rank)
        return tuple(ranked_candidates)

    @staticmethod
    def _confidence_from_evaluation(
        evaluation: DecisionEvaluationDB,
        candidates_by_row_id: dict[int, CandidateAction],
    ) -> DecisionConfidenceResult | None:
        confidence_row = evaluation.confidence_artifact
        if confidence_row is None:
            return None
        if confidence_row.decision_evaluation_id != evaluation.id:
            raise DecisionPersistenceIntegrityError(
                "confidence row belongs to another decision evaluation"
            )
        candidate = candidates_by_row_id.get(confidence_row.candidate_id)
        if candidate is None:
            raise DecisionPersistenceIntegrityError(
                "confidence references candidate outside this decision evaluation"
            )

        evidence_inputs = _EVIDENCE_INPUTS.validate_json(
            confidence_row.evidence_inputs_json
        )
        limitations = _CONFIDENCE_LIMITATIONS.validate_json(
            confidence_row.limitations_json
        )
        return DecisionConfidenceResult(
            candidate_id=candidate.id,
            evidence_inputs=evidence_inputs,
            context_freshness=FreshnessLevel(
                confidence_row.context_freshness
            ),
            miner_freshness=FreshnessLevel(confidence_row.miner_freshness),
            hardware_freshness=FreshnessLevel(
                confidence_row.hardware_freshness
            ),
            prediction_reliability=confidence_row.prediction_reliability,
            overall_confidence=confidence_row.overall_confidence,
            limitations=limitations,
        )

    @staticmethod
    def _explanation_from_evaluation(
        evaluation: DecisionEvaluationDB,
    ) -> DecisionExplanation | None:
        explanation_row = evaluation.explanation
        if explanation_row is None:
            return None
        if explanation_row.decision_evaluation_id != evaluation.id:
            raise DecisionPersistenceIntegrityError(
                "explanation row belongs to another decision evaluation"
            )
        explanation = DecisionExplanation.model_validate_json(
            explanation_row.explanation_json
        )
        if explanation.decision_id != evaluation.decision_id:
            raise DecisionPersistenceIntegrityError(
                "DecisionExplanation.decision_id disagrees with persisted evaluation"
            )
        if explanation.decision_state != evaluation.state:
            raise DecisionPersistenceIntegrityError(
                "DecisionExplanation.decision_state disagrees with persisted evaluation"
            )
        return explanation

    def _validate_artifacts(
        self,
        artifacts: DecisionEvaluationArtifacts,
    ) -> dict[str, tuple[str, int | None]]:
        candidate_by_id = self._index_candidates(artifacts.candidates)
        membership = self._validate_membership(artifacts.result, candidate_by_id)
        self._validate_policy_results(artifacts.policy_results, candidate_by_id)
        self._validate_predictions(artifacts.predictions, candidate_by_id)
        self._validate_scores(artifacts.scores, candidate_by_id)
        self._validate_ranking(
            artifacts.ranking,
            candidate_by_id,
            artifacts.scores,
        )
        self._validate_confidence(
            artifacts.confidence,
            candidate_by_id,
        )
        self._validate_explanation(artifacts.explanation, artifacts.result)
        return membership

    @staticmethod
    def _index_candidates(
        candidates: tuple[CandidateAction, ...],
    ) -> dict[str, CandidateAction]:
        candidate_by_id: dict[str, CandidateAction] = {}
        for candidate in candidates:
            if candidate.id in candidate_by_id:
                raise DecisionPersistenceIntegrityError(
                    f"duplicate candidate domain id: {candidate.id}"
                )
            candidate_by_id[candidate.id] = candidate
        return candidate_by_id

    @classmethod
    def _validate_membership(
        cls,
        result: DecisionResult,
        candidate_by_id: dict[str, CandidateAction],
    ) -> dict[str, tuple[str, int | None]]:
        membership: dict[str, tuple[str, int | None]] = {}

        if result.selected_action is not None:
            cls._add_membership(
                result.selected_action,
                "selected",
                None,
                membership,
                candidate_by_id,
            )

        for position, candidate in enumerate(result.alternatives):
            cls._add_membership(
                candidate,
                "alternative",
                position,
                membership,
                candidate_by_id,
            )

        for position, candidate in enumerate(result.rejected_alternatives):
            cls._add_membership(
                candidate,
                "rejected",
                position,
                membership,
                candidate_by_id,
            )

        supplied_ids = set(candidate_by_id)
        member_ids = set(membership)
        if member_ids != supplied_ids:
            missing = sorted(supplied_ids - member_ids)
            unknown = sorted(member_ids - supplied_ids)
            details: list[str] = []
            if missing:
                details.append("without_result_role=" + ",".join(missing))
            if unknown:
                details.append("unknown=" + ",".join(unknown))
            raise DecisionPersistenceIntegrityError(
                "DecisionResult membership must exactly cover supplied candidates"
                + (": " + "; ".join(details) if details else "")
            )

        return membership

    @staticmethod
    def _add_membership(
        candidate: CandidateAction,
        role: str,
        position: int | None,
        membership: dict[str, tuple[str, int | None]],
        candidate_by_id: dict[str, CandidateAction],
    ) -> None:
        canonical = candidate_by_id.get(candidate.id)
        if canonical is None:
            raise DecisionPersistenceIntegrityError(
                f"DecisionResult references unknown candidate id: {candidate.id}"
            )
        if canonical != candidate:
            raise DecisionPersistenceIntegrityError(
                f"DecisionResult candidate differs from supplied candidate: {candidate.id}"
            )
        if candidate.id in membership:
            raise DecisionPersistenceIntegrityError(
                f"candidate appears in multiple DecisionResult roles: {candidate.id}"
            )
        membership[candidate.id] = (role, position)

    @staticmethod
    def _validate_policy_results(
        policy_results: dict[str, PolicyResult],
        candidate_by_id: dict[str, CandidateAction],
    ) -> None:
        unknown = sorted(set(policy_results) - set(candidate_by_id))
        if unknown:
            raise DecisionPersistenceIntegrityError(
                "policy result references unknown candidate id(s): " + ", ".join(unknown)
            )

    @staticmethod
    def _validate_predictions(
        predictions: dict[str, PredictionResult],
        candidate_by_id: dict[str, CandidateAction],
    ) -> None:
        unknown = sorted(set(predictions) - set(candidate_by_id))
        if unknown:
            raise DecisionPersistenceIntegrityError(
                "prediction references unknown candidate id(s): " + ", ".join(unknown)
            )
        for candidate_id, prediction in predictions.items():
            if prediction.candidate_id != candidate_id:
                raise DecisionPersistenceIntegrityError(
                    "prediction mapping key must match PredictionResult.candidate_id"
                )

    @staticmethod
    def _validate_scores(
        scores: dict[str, DecisionScore],
        candidate_by_id: dict[str, CandidateAction],
    ) -> None:
        unknown = sorted(set(scores) - set(candidate_by_id))
        if unknown:
            raise DecisionPersistenceIntegrityError(
                "score references unknown candidate id(s): " + ", ".join(unknown)
            )
        for candidate_id, score in scores.items():
            if score.candidate_id != candidate_id:
                raise DecisionPersistenceIntegrityError(
                    "score mapping key must match DecisionScore.candidate_id"
                )

    @staticmethod
    def _validate_ranking(
        ranking: tuple[RankedCandidate, ...],
        candidate_by_id: dict[str, CandidateAction],
        scores: dict[str, DecisionScore],
    ) -> None:
        ranked_ids: set[str] = set()
        ranks: set[int] = set()

        for item in ranking:
            candidate_id = item.candidate.id
            canonical = candidate_by_id.get(candidate_id)
            if canonical is None:
                raise DecisionPersistenceIntegrityError(
                    f"ranking references unknown candidate id: {candidate_id}"
                )
            if canonical != item.candidate:
                raise DecisionPersistenceIntegrityError(
                    f"ranked candidate differs from supplied candidate: {candidate_id}"
                )
            if candidate_id in ranked_ids:
                raise DecisionPersistenceIntegrityError(
                    f"ranking contains duplicate candidate id: {candidate_id}"
                )
            if item.rank in ranks:
                raise DecisionPersistenceIntegrityError(
                    f"ranking contains duplicate rank position: {item.rank}"
                )
            if item.score.candidate_id != candidate_id:
                raise DecisionPersistenceIntegrityError(
                    "RankedCandidate score candidate_id must match ranked candidate id"
                )

            supplied_score = scores.get(candidate_id)
            if supplied_score is None:
                raise DecisionPersistenceIntegrityError(
                    f"ranking candidate missing supplied DecisionScore: {candidate_id}"
                )
            if supplied_score != item.score:
                raise DecisionPersistenceIntegrityError(
                    f"RankedCandidate score differs from supplied DecisionScore: {candidate_id}"
                )

            ranked_ids.add(candidate_id)
            ranks.add(item.rank)

    @staticmethod
    def _validate_confidence(
        confidence: DecisionConfidenceResult | None,
        candidate_by_id: dict[str, CandidateAction],
    ) -> None:
        if confidence is None:
            return

        if confidence.candidate_id not in candidate_by_id:
            raise DecisionPersistenceIntegrityError(
                f"confidence references unknown candidate id: {confidence.candidate_id}"
            )

    @staticmethod
    def _validate_explanation(
        explanation: DecisionExplanation | None,
        result: DecisionResult,
    ) -> None:
        if explanation is None:
            return
        if explanation.decision_id != result.decision_id:
            raise DecisionPersistenceIntegrityError(
                "DecisionExplanation.decision_id must match DecisionResult.decision_id"
            )
        if explanation.decision_state != result.state:
            raise DecisionPersistenceIntegrityError(
                "DecisionExplanation.decision_state must match DecisionResult.state"
            )

    def _ensure_new_decision_id(self, decision_id: str) -> None:
        existing = self.session.execute(
            select(DecisionEvaluationDB.id).where(
                DecisionEvaluationDB.decision_id == decision_id
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise DecisionPersistenceIntegrityError(
                f"decision evaluation already exists: {decision_id}"
            )

    def _persist_candidates(
        self,
        *,
        evaluation: DecisionEvaluationDB,
        candidates: tuple[CandidateAction, ...],
        membership: dict[str, tuple[str, int | None]],
    ) -> dict[str, DecisionCandidateDB]:
        rows: dict[str, DecisionCandidateDB] = {}
        for candidate in candidates:
            role, position = membership[candidate.id]
            row = DecisionCandidateDB(
                decision_evaluation_id=evaluation.id,
                candidate_id=candidate.id,
                action_type=candidate.action_type.value,
                execution_category=candidate.execution_category.value,
                description=candidate.description,
                expected_gain=candidate.expected_gain,
                confidence=candidate.confidence,
                risk_score=candidate.risk_score,
                transition_cost=candidate.transition_cost,
                reversible=candidate.reversible,
                result_role=role,
                result_position=position,
            )
            self.session.add(row)
            rows[candidate.id] = row
        return rows

    def _persist_policy_results(
        self,
        policy_results: dict[str, PolicyResult],
        candidate_rows: dict[str, DecisionCandidateDB],
    ) -> None:
        for candidate_id, policy_result in policy_results.items():
            self.session.add(
                DecisionPolicyResultDB(
                    candidate_id=self._row_id(candidate_rows[candidate_id]),
                    allowed=policy_result.allowed,
                    violations_json=json.dumps(policy_result.violations),
                )
            )

    def _persist_predictions(
        self,
        predictions: dict[str, PredictionResult],
        candidate_rows: dict[str, DecisionCandidateDB],
    ) -> None:
        for candidate_id, prediction in predictions.items():
            self.session.add(
                DecisionPredictionDB(
                    candidate_id=self._row_id(candidate_rows[candidate_id]),
                    expected_reward_change=prediction.expected_reward_change,
                    expected_hashrate_change=prediction.expected_hashrate_change,
                    expected_power_change=prediction.expected_power_change,
                    confidence=prediction.confidence,
                    uncertainty=prediction.uncertainty,
                    horizon=prediction.horizon.value,
                    rationale=prediction.rationale,
                )
            )

    def _persist_scores(
        self,
        scores: dict[str, DecisionScore],
        candidate_rows: dict[str, DecisionCandidateDB],
    ) -> None:
        for candidate_id, score in scores.items():
            self.session.add(
                DecisionScoreDB(
                    candidate_id=self._row_id(candidate_rows[candidate_id]),
                    benefit=score.benefit,
                    confidence=score.confidence,
                    risk=score.risk,
                    action_cost=score.action_cost,
                    uncertainty=score.uncertainty,
                    utility_score=score.utility_score,
                )
            )

    def _persist_rankings(
        self,
        evaluation: DecisionEvaluationDB,
        ranking: tuple[RankedCandidate, ...],
        candidate_rows: dict[str, DecisionCandidateDB],
    ) -> list[DecisionRankingDB]:
        rows: list[DecisionRankingDB] = []
        for item in ranking:
            row = DecisionRankingDB(
                decision_evaluation_id=evaluation.id,
                candidate_id=self._row_id(candidate_rows[item.candidate.id]),
                rank_position=item.rank,
            )
            self.session.add(row)
            rows.append(row)
        return rows

    def _persist_confidence(
        self,
        evaluation: DecisionEvaluationDB,
        confidence: DecisionConfidenceResult | None,
        candidate_rows: dict[str, DecisionCandidateDB],
    ) -> DecisionConfidenceDB | None:
        if confidence is None:
            return None

        row = DecisionConfidenceDB(
            decision_evaluation_id=evaluation.id,
            candidate_id=self._row_id(candidate_rows[confidence.candidate_id]),
            evidence_inputs_json=json.dumps(
                [item.model_dump(mode="json") for item in confidence.evidence_inputs]
            ),
            context_freshness=confidence.context_freshness.value,
            miner_freshness=confidence.miner_freshness.value,
            hardware_freshness=confidence.hardware_freshness.value,
            prediction_reliability=confidence.prediction_reliability,
            overall_confidence=confidence.overall_confidence,
            limitations_json=json.dumps(
                [limitation.value for limitation in confidence.limitations]
            ),
        )
        self.session.add(row)
        return row

    def _persist_explanation(
        self,
        evaluation: DecisionEvaluationDB,
        explanation_json: str | None,
    ) -> None:
        if explanation_json is None:
            return
        self.session.add(
            DecisionExplanationDB(
                decision_evaluation_id=evaluation.id,
                explanation_json=explanation_json,
            )
        )

    @staticmethod
    def _require_owned_candidate(
        evaluation: DecisionEvaluationDB,
        candidate: DecisionCandidateDB,
        artifact_name: str,
    ) -> None:
        if candidate.decision_evaluation_id != evaluation.id:
            raise DecisionPersistenceIntegrityError(
                f"{artifact_name} candidate row belongs to another decision evaluation"
            )

    @staticmethod
    def _validate_persisted_ownership(
        *,
        evaluation: DecisionEvaluationDB,
        candidate_rows: dict[str, DecisionCandidateDB],
        ranking_rows: list[DecisionRankingDB],
        confidence_row: DecisionConfidenceDB | None,
    ) -> None:
        evaluation_id = evaluation.id
        if evaluation_id is None:
            raise DecisionPersistenceIntegrityError(
                "decision evaluation persistence identity is unavailable"
            )

        for row in candidate_rows.values():
            if row.decision_evaluation_id != evaluation_id:
                raise DecisionPersistenceIntegrityError(
                    "candidate row belongs to another decision evaluation"
                )

        if evaluation.selected_candidate_id is not None:
            selected_rows = [
                row
                for row in candidate_rows.values()
                if row.id == evaluation.selected_candidate_id
            ]
            if len(selected_rows) != 1:
                raise DecisionPersistenceIntegrityError(
                    "selected candidate row does not belong to this decision evaluation"
                )

        candidate_row_ids = {
            DecisionEvaluationRepository._row_id(row)
            for row in candidate_rows.values()
        }
        for ranking_row in ranking_rows:
            if ranking_row.decision_evaluation_id != evaluation_id:
                raise DecisionPersistenceIntegrityError(
                    "ranking row belongs to another decision evaluation"
                )
            if ranking_row.candidate_id not in candidate_row_ids:
                raise DecisionPersistenceIntegrityError(
                    "ranking candidate row belongs to another decision evaluation"
                )

        if confidence_row is not None:
            if confidence_row.decision_evaluation_id != evaluation_id:
                raise DecisionPersistenceIntegrityError(
                    "confidence row belongs to another decision evaluation"
                )
            if confidence_row.candidate_id not in candidate_row_ids:
                raise DecisionPersistenceIntegrityError(
                    "confidence candidate row belongs to another decision evaluation"
                )

    @staticmethod
    def _row_id(row: DecisionCandidateDB) -> int:
        if row.id is None:
            raise DecisionPersistenceIntegrityError(
                "candidate persistence identity is unavailable"
            )
        return row.id
