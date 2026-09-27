"""Deterministic orchestration for the M2.2.2 decision pipeline."""

from collections.abc import Callable

from .candidates import CandidateGenerator
from .confidence import DecisionConfidenceEngine, DecisionConfidenceResult
from .context import DecisionContext
from .lifecycle import DecisionState
from .models import CandidateAction, DecisionResult
from .policies import DecisionPolicy, PolicyResult, evaluate_policy
from .predictors import OutcomePredictor, PredictionResult
from .ranking import DecisionRanker, RankedCandidate
from .scoring import DecisionScore, DecisionScorer

PolicyEvaluator = Callable[
    [DecisionPolicy, CandidateAction, DecisionContext],
    PolicyResult,
]


class NoAdmissibleCandidateError(ValueError):
    """Raised when policy admission leaves no candidate available to propose."""


class DecisionEngine:
    """Compose existing decision components without changing their semantics."""

    def __init__(
        self,
        *,
        candidate_generator: CandidateGenerator,
        policy: DecisionPolicy,
        predictor: OutcomePredictor,
        scorer: DecisionScorer,
        ranker: DecisionRanker,
        confidence_engine: DecisionConfidenceEngine,
        policy_evaluator: PolicyEvaluator = evaluate_policy,
    ) -> None:
        self._candidate_generator = candidate_generator
        self._policy = policy
        self._predictor = predictor
        self._scorer = scorer
        self._ranker = ranker
        self._confidence_engine = confidence_engine
        self._policy_evaluator = policy_evaluator

    def evaluate(self, context: DecisionContext) -> DecisionResult:
        """Return a deterministic proposal from the existing Phase 1-9 pipeline."""

        candidates = self._candidate_generator.generate(context)
        self._ensure_unique_candidate_ids(candidates)

        approved: list[CandidateAction] = []
        rejected: list[CandidateAction] = []
        rejection_results: dict[str, PolicyResult] = {}

        for candidate in candidates:
            policy_result = self._policy_evaluator(
                self._policy,
                candidate,
                context,
            )
            if not isinstance(policy_result, PolicyResult):
                raise TypeError("policy evaluator must return PolicyResult")
            if policy_result.allowed:
                approved.append(candidate)
            else:
                rejected.append(candidate)
                rejection_results[candidate.id] = policy_result

        if not approved:
            raise NoAdmissibleCandidateError(
                "policy admission left no candidate available for decision proposal"
            )

        predictions: dict[str, PredictionResult] = {}
        scores: list[DecisionScore] = []

        for candidate in approved:
            prediction = self._predictor.predict(context, candidate)
            if prediction.candidate_id != candidate.id:
                raise ValueError(
                    "prediction candidate_id must match policy-approved candidate id"
                )
            predictions[candidate.id] = prediction

            score = self._scorer.score(candidate, prediction)
            if score.candidate_id != candidate.id:
                raise ValueError(
                    "DecisionScore candidate_id must match policy-approved candidate id"
                )
            scores.append(score)

        ranked = self._ranker.rank(approved, scores)
        self._validate_ranking(ranked, approved, scores)

        selected_ranked = ranked[0]
        selected = selected_ranked.candidate
        alternatives = [item.candidate for item in ranked[1:]]
        selected_prediction = predictions[selected.id]

        confidence_result = self._confidence_engine.evaluate(
            context,
            selected_prediction,
        )
        if confidence_result.candidate_id != selected.id:
            raise ValueError(
                "confidence result candidate_id must match selected candidate id"
            )

        confidence_value, confidence_source = self._decision_result_confidence(
            confidence_result
        )

        return DecisionResult(
            decision_id=f"decision-{selected.id}",
            state=DecisionState.APPROVED.value,
            selected_action=selected,
            alternatives=alternatives,
            rejected_alternatives=rejected,
            confidence=confidence_value,
            explanation=self._build_explanation(
                selected=selected,
                alternatives=alternatives,
                rejected=rejected,
                rejection_results=rejection_results,
                confidence_result=confidence_result,
                confidence_source=confidence_source,
            ),
        )

    @staticmethod
    def _decision_result_confidence(
        confidence_result: DecisionConfidenceResult,
    ) -> tuple[float, str]:
        """Map the strongest available Phase 9 numeric component without aggregation."""

        if confidence_result.overall_confidence is not None:
            return confidence_result.overall_confidence, "overall_confidence"
        return confidence_result.prediction_reliability, "prediction_reliability"

    @staticmethod
    def _ensure_unique_candidate_ids(candidates: list[CandidateAction]) -> None:
        seen: set[str] = set()
        for candidate in candidates:
            if candidate.id in seen:
                raise ValueError(f"duplicate candidate id: {candidate.id}")
            seen.add(candidate.id)

    @staticmethod
    def _validate_ranking(
        ranked: list[RankedCandidate],
        approved: list[CandidateAction],
        scores: list[DecisionScore],
    ) -> None:
        approved_ids = {candidate.id for candidate in approved}
        score_by_id = {score.candidate_id: score for score in scores}

        if len(ranked) != len(approved):
            raise ValueError("ranking must contain every policy-approved candidate exactly once")

        ranked_ids: list[str] = []
        for item in ranked:
            candidate_id = item.candidate.id
            ranked_ids.append(candidate_id)
            if candidate_id not in approved_ids:
                raise ValueError(
                    f"ranking references unknown candidate id: {candidate_id}"
                )
            expected_score = score_by_id.get(candidate_id)
            if expected_score is None:
                raise ValueError(
                    f"ranking candidate missing DecisionScore: {candidate_id}"
                )
            if item.score.candidate_id != candidate_id:
                raise ValueError(
                    "ranked DecisionScore candidate_id must match ranked candidate id"
                )
            if item.score != expected_score:
                raise ValueError(
                    f"ranking altered DecisionScore for candidate id: {candidate_id}"
                )

        if len(set(ranked_ids)) != len(ranked_ids):
            raise ValueError("ranking contains duplicate candidate ids")
        if set(ranked_ids) != approved_ids:
            raise ValueError("ranking candidate identities do not match approved candidates")

    @staticmethod
    def _build_explanation(
        *,
        selected: CandidateAction,
        alternatives: list[CandidateAction],
        rejected: list[CandidateAction],
        rejection_results: dict[str, PolicyResult],
        confidence_result: DecisionConfidenceResult,
        confidence_source: str,
    ) -> str:
        limitation_values = ",".join(
            limitation.value for limitation in confidence_result.limitations
        ) or "none"
        rejection_values = ",".join(
            f"{candidate.id}:{'|'.join(rejection_results[candidate.id].violations)}"
            for candidate in rejected
        ) or "none"
        return (
            f"selected={selected.id};"
            f"eligible_alternatives={len(alternatives)};"
            f"rejected_alternatives={len(rejected)};"
            f"rejections={rejection_values};"
            f"confidence_source={confidence_source};"
            f"confidence_limitations={limitation_values}"
        )
