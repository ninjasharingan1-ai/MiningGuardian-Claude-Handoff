"""Deterministic ordering for already-scored decision candidates."""

from pydantic import BaseModel, Field

from .models import ActionType, CandidateAction
from .scoring import DecisionScore


class RankedCandidate(BaseModel):
    """One candidate's position in a deterministic ranking."""

    rank: int = Field(ge=1)
    candidate: CandidateAction
    score: DecisionScore


class DecisionRanker:
    """Order policy-approved, pre-scored candidates without rescoring them."""

    def rank(
        self,
        candidates: list[CandidateAction],
        scores: list[DecisionScore],
    ) -> list[RankedCandidate]:
        """Return one-based ranking using utility score and ADR tie-break rules."""

        candidate_by_id = self._index_candidates(candidates)
        score_by_id = self._index_scores(scores)

        unknown_score_ids = sorted(set(score_by_id) - set(candidate_by_id))
        if unknown_score_ids:
            raise ValueError(
                "score references unknown candidate id(s): "
                + ", ".join(unknown_score_ids)
            )

        missing_score_ids = sorted(set(candidate_by_id) - set(score_by_id))
        if missing_score_ids:
            raise ValueError(
                "candidate missing DecisionScore: " + ", ".join(missing_score_ids)
            )

        action_type_order = {
            action_type: index for index, action_type in enumerate(ActionType)
        }

        ordered = sorted(
            candidates,
            key=lambda candidate: self._ranking_key(
                candidate,
                score_by_id[candidate.id],
                action_type_order,
            ),
        )

        return [
            RankedCandidate(
                rank=index,
                candidate=candidate,
                score=score_by_id[candidate.id],
            )
            for index, candidate in enumerate(ordered, start=1)
        ]

    @staticmethod
    def _index_candidates(
        candidates: list[CandidateAction],
    ) -> dict[str, CandidateAction]:
        candidate_by_id: dict[str, CandidateAction] = {}
        for candidate in candidates:
            if candidate.id in candidate_by_id:
                raise ValueError(f"duplicate candidate id: {candidate.id}")
            candidate_by_id[candidate.id] = candidate
        return candidate_by_id

    @staticmethod
    def _index_scores(scores: list[DecisionScore]) -> dict[str, DecisionScore]:
        score_by_id: dict[str, DecisionScore] = {}
        for score in scores:
            if score.candidate_id in score_by_id:
                raise ValueError(
                    f"duplicate DecisionScore for candidate id: {score.candidate_id}"
                )
            score_by_id[score.candidate_id] = score
        return score_by_id

    @staticmethod
    def _ranking_key(
        candidate: CandidateAction,
        score: DecisionScore,
        action_type_order: dict[ActionType, int],
    ) -> tuple[float, float, float, float, bool, int, str]:
        return (
            -score.utility_score,
            score.risk,
            -score.confidence,
            score.action_cost,
            not candidate.reversible,
            action_type_order[candidate.action_type],
            candidate.id,
        )
