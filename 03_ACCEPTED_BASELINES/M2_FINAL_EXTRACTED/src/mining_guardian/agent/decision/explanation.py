"""Deterministic structured explanations for decision pipeline artifacts."""

from collections.abc import Mapping, Sequence
from enum import StrEnum

from pydantic import BaseModel, Field

from ..cognition.enums import (
    ClaimStatus,
    ClaimType,
    EvidenceType,
    HypothesisStatus,
    Reliability,
)
from ..temporal import FreshnessLevel
from .confidence import DecisionConfidenceResult
from .context import DecisionContext
from .models import CandidateAction, DecisionResult
from .policies import PolicyResult
from .ranking import RankedCandidate
from .scoring import DecisionScore


class ExplanationLimitation(StrEnum):
    """Stable identifiers for explanation information that is unavailable."""

    REJECTION_REASON_UNAVAILABLE = "rejection_reason_unavailable"
    CANDIDATE_PROVENANCE_INCOMPLETE = "candidate_provenance_incomplete"
    AGGREGATE_CONFIDENCE_UNAVAILABLE = "aggregate_confidence_unavailable"
    SELECTED_SCORE_UNAVAILABLE = "selected_score_unavailable"
    NO_SELECTED_ACTION = "no_selected_action"


class EvidenceTrace(BaseModel):
    """Minimal evidence provenance exposed without raw telemetry payloads."""

    evidence_id: str
    evidence_type: EvidenceType
    reliability: Reliability
    freshness: FreshnessLevel
    limitations: list[str] = Field(default_factory=list)


class ClaimTrace(BaseModel):
    """Minimal claim provenance for auditability."""

    claim_id: str
    claim_type: ClaimType
    status: ClaimStatus
    supporting_evidence_ids: list[str] = Field(default_factory=list)


class HypothesisTrace(BaseModel):
    """Minimal hypothesis provenance for auditability."""

    hypothesis_id: str
    status: HypothesisStatus
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence_ids: list[str] = Field(default_factory=list)


class CognitiveTrace(BaseModel):
    """Context-level cognitive basis without inferred candidate provenance."""

    evidence: list[EvidenceTrace] = Field(default_factory=list)
    claims: list[ClaimTrace] = Field(default_factory=list)
    hypotheses: list[HypothesisTrace] = Field(default_factory=list)
    context_freshness: FreshnessLevel
    miner_freshness: FreshnessLevel
    hardware_freshness: FreshnessLevel


class CandidateExplanation(BaseModel):
    """Eligible candidate with its preserved rank and ADR-0006 score when available."""

    rank: int | None = Field(default=None, ge=1)
    candidate: CandidateAction
    score: DecisionScore | None = None
    reason: str | None = None


class RejectedCandidateExplanation(BaseModel):
    """Policy-rejected candidate and only the preserved rejection facts."""

    candidate: CandidateAction
    policy_violations: list[str] = Field(default_factory=list)
    limitations: list[ExplanationLimitation] = Field(default_factory=list)


class DecisionExplanation(BaseModel):
    """Structured, auditable projection of existing decision artifacts."""

    decision_id: str
    decision_state: str
    selected: CandidateExplanation | None = None
    alternatives: list[CandidateExplanation] = Field(default_factory=list)
    rejected_alternatives: list[RejectedCandidateExplanation] = Field(
        default_factory=list
    )
    confidence: DecisionConfidenceResult | None = None
    cognitive_trace: CognitiveTrace | None = None
    limitations: list[ExplanationLimitation] = Field(default_factory=list)

    def render_text(self) -> str:
        """Render deterministic text from structured explanation data."""

        selected_id = self.selected.candidate.id if self.selected else "none"
        selected_rank = (
            str(self.selected.rank)
            if self.selected and self.selected.rank is not None
            else "unavailable"
        )
        selected_utility = (
            repr(self.selected.score.utility_score)
            if self.selected and self.selected.score is not None
            else "unavailable"
        )
        confidence_value = (
            repr(self.confidence.overall_confidence)
            if self.confidence and self.confidence.overall_confidence is not None
            else "unavailable"
        )
        limitation_values = ",".join(item.value for item in self.limitations) or "none"
        return (
            f"decision={self.decision_id};"
            f"state={self.decision_state};"
            f"selected={selected_id};"
            f"selected_rank={selected_rank};"
            f"utility_score={selected_utility};"
            f"eligible_alternatives={len(self.alternatives)};"
            f"rejected_alternatives={len(self.rejected_alternatives)};"
            f"overall_confidence={confidence_value};"
            f"limitations={limitation_values}"
        )


class DecisionExplainer:
    """Project existing pipeline artifacts into a deterministic explanation."""

    def explain(
        self,
        result: DecisionResult,
        *,
        ranking: Sequence[RankedCandidate] = (),
        confidence: DecisionConfidenceResult | None = None,
        policy_results: Mapping[str, PolicyResult] | None = None,
        context: DecisionContext | None = None,
    ) -> DecisionExplanation:
        """Explain supplied artifacts without new reasoning or recalculation."""

        ranked_by_id = self._index_ranking(ranking)
        policy_results = policy_results or {}
        self._validate_result_partition(result)
        self._validate_policy_results(result, policy_results)
        limitations: list[ExplanationLimitation] = []

        selected = self._selected_explanation(
            result,
            ranked_by_id,
            limitations,
        )
        alternatives = self._alternative_explanations(
            result,
            ranked_by_id,
        )
        rejected = self._rejected_explanations(
            result.rejected_alternatives,
            policy_results,
        )
        self._validate_ranking_consistency(result, ranked_by_id)

        if confidence is not None:
            if result.selected_action is None:
                raise ValueError(
                    "confidence artifact requires a selected candidate"
                )
            if confidence.candidate_id != result.selected_action.id:
                raise ValueError(
                    "confidence candidate_id must match selected candidate id"
                )
            if confidence.overall_confidence is None:
                limitations.append(
                    ExplanationLimitation.AGGREGATE_CONFIDENCE_UNAVAILABLE
                )

        cognitive_trace = self._build_cognitive_trace(context)
        if context is not None and result.selected_action is not None:
            limitations.append(
                ExplanationLimitation.CANDIDATE_PROVENANCE_INCOMPLETE
            )

        if result.selected_action is None:
            limitations.append(ExplanationLimitation.NO_SELECTED_ACTION)

        return DecisionExplanation(
            decision_id=result.decision_id,
            decision_state=result.state,
            selected=selected,
            alternatives=alternatives,
            rejected_alternatives=rejected,
            confidence=confidence,
            cognitive_trace=cognitive_trace,
            limitations=self._unique_limitations(limitations),
        )


    @staticmethod
    def _validate_result_partition(result: DecisionResult) -> None:
        """Reject duplicate or contradictory candidate membership in DecisionResult."""

        selected_ids = (
            {result.selected_action.id} if result.selected_action is not None else set()
        )
        alternative_ids = [candidate.id for candidate in result.alternatives]
        rejected_ids = [candidate.id for candidate in result.rejected_alternatives]

        if len(set(alternative_ids)) != len(alternative_ids):
            raise ValueError("DecisionResult contains duplicate eligible alternative ids")
        if len(set(rejected_ids)) != len(rejected_ids):
            raise ValueError("DecisionResult contains duplicate rejected alternative ids")

        alternative_id_set = set(alternative_ids)
        rejected_id_set = set(rejected_ids)

        if selected_ids & alternative_id_set:
            raise ValueError(
                "selected candidate cannot also appear in eligible alternatives"
            )
        if selected_ids & rejected_id_set:
            raise ValueError(
                "selected candidate cannot also appear in rejected alternatives"
            )
        if alternative_id_set & rejected_id_set:
            raise ValueError(
                "candidate cannot appear in both eligible and rejected alternatives"
            )
        if result.selected_action is None and result.alternatives:
            raise ValueError(
                "DecisionResult cannot contain eligible alternatives without a selected candidate"
            )

    @staticmethod
    def _validate_ranking_consistency(
        result: DecisionResult,
        ranked_by_id: dict[str, RankedCandidate],
    ) -> None:
        """Ensure supplied ranking is a complete projection of eligible candidates."""

        if not ranked_by_id:
            return

        expected_order: list[str] = []
        if result.selected_action is not None:
            expected_order.append(result.selected_action.id)
        expected_order.extend(candidate.id for candidate in result.alternatives)
        expected_ids = set(expected_order)

        ranked_ids = set(ranked_by_id)
        if ranked_ids != expected_ids:
            unexpected = [
                candidate_id
                for candidate_id in ranked_by_id
                if candidate_id not in expected_ids
            ]
            missing = [
                candidate_id
                for candidate_id in expected_order
                if candidate_id not in ranked_ids
            ]
            details: list[str] = []
            if unexpected:
                details.append("unexpected=" + ",".join(unexpected))
            if missing:
                details.append("missing=" + ",".join(missing))
            raise ValueError(
                "ranking candidates must exactly match DecisionResult eligible candidates"
                + (": " + "; ".join(details) if details else "")
            )

        ranks = {item.rank for item in ranked_by_id.values()}
        expected_ranks = set(range(1, len(ranked_by_id) + 1))
        if ranks != expected_ranks:
            raise ValueError("ranking positions must be contiguous starting at 1")

    @staticmethod
    def _validate_policy_results(
        result: DecisionResult,
        policy_results: Mapping[str, PolicyResult],
    ) -> None:
        """Reject policy artifacts that contradict DecisionResult membership."""

        eligible_ids = {candidate.id for candidate in result.alternatives}
        if result.selected_action is not None:
            eligible_ids.add(result.selected_action.id)
        rejected_ids = {candidate.id for candidate in result.rejected_alternatives}
        known_ids = eligible_ids | rejected_ids

        unknown_ids = [
            candidate_id for candidate_id in policy_results if candidate_id not in known_ids
        ]
        if unknown_ids:
            raise ValueError(
                "policy result references unknown DecisionResult candidate id(s): "
                + ", ".join(unknown_ids)
            )

        for candidate_id, policy_result in policy_results.items():
            if policy_result.allowed and policy_result.violations:
                raise ValueError(
                    "allowed PolicyResult cannot contain policy violations"
                )
            if not policy_result.allowed and not policy_result.violations:
                raise ValueError(
                    "rejected PolicyResult must contain at least one violation"
                )
            if candidate_id in eligible_ids and not policy_result.allowed:
                raise ValueError(
                    "eligible candidate cannot have a rejected PolicyResult"
                )
            if candidate_id in rejected_ids and policy_result.allowed:
                raise ValueError(
                    "rejected alternative cannot have an allowed PolicyResult"
                )

    @staticmethod
    def _index_ranking(
        ranking: Sequence[RankedCandidate],
    ) -> dict[str, RankedCandidate]:
        indexed: dict[str, RankedCandidate] = {}
        ranks: set[int] = set()
        for item in ranking:
            candidate_id = item.candidate.id
            if candidate_id in indexed:
                raise ValueError(f"duplicate ranked candidate id: {candidate_id}")
            if item.rank in ranks:
                raise ValueError(f"duplicate ranking position: {item.rank}")
            if item.score.candidate_id != candidate_id:
                raise ValueError(
                    "ranked DecisionScore candidate_id must match ranked candidate id"
                )
            indexed[candidate_id] = item
            ranks.add(item.rank)
        return indexed

    @staticmethod
    def _selected_explanation(
        result: DecisionResult,
        ranked_by_id: dict[str, RankedCandidate],
        limitations: list[ExplanationLimitation],
    ) -> CandidateExplanation | None:
        selected = result.selected_action
        if selected is None:
            return None

        ranked = ranked_by_id.get(selected.id)
        if ranked is None:
            limitations.append(ExplanationLimitation.SELECTED_SCORE_UNAVAILABLE)
            return CandidateExplanation(
                candidate=selected,
                reason="selected_candidate_from_decision_result",
            )
        if ranked.candidate != selected:
            raise ValueError("ranked selected candidate does not match DecisionResult")
        if ranked.rank != 1:
            raise ValueError("selected candidate must be rank 1 when ranking is supplied")

        return CandidateExplanation(
            rank=ranked.rank,
            candidate=selected,
            score=ranked.score,
            reason="highest_ranked_eligible_candidate",
        )

    @staticmethod
    def _alternative_explanations(
        result: DecisionResult,
        ranked_by_id: dict[str, RankedCandidate],
    ) -> list[CandidateExplanation]:
        explanations: list[CandidateExplanation] = []
        for candidate in result.alternatives:
            ranked = ranked_by_id.get(candidate.id)
            if ranked is None:
                raise ValueError(
                    f"eligible alternative missing ranking artifact: {candidate.id}"
                )
            if ranked.candidate != candidate:
                raise ValueError(
                    f"ranked candidate does not match alternative: {candidate.id}"
                )
            explanations.append(
                CandidateExplanation(
                    rank=ranked.rank,
                    candidate=candidate,
                    score=ranked.score,
                )
            )

        explanations.sort(
            key=lambda item: (
                ranked_by_id[item.candidate.id].rank is None,
                ranked_by_id[item.candidate.id].rank
                if ranked_by_id[item.candidate.id].rank is not None
                else 0,
            )
        )
        return explanations

    @staticmethod
    def _rejected_explanations(
        rejected_candidates: Sequence[CandidateAction],
        policy_results: Mapping[str, PolicyResult],
    ) -> list[RejectedCandidateExplanation]:
        explanations: list[RejectedCandidateExplanation] = []
        for candidate in rejected_candidates:
            policy_result = policy_results.get(candidate.id)
            if policy_result is None:
                explanations.append(
                    RejectedCandidateExplanation(
                        candidate=candidate,
                        limitations=[
                            ExplanationLimitation.REJECTION_REASON_UNAVAILABLE
                        ],
                    )
                )
                continue
            if policy_result.allowed:
                raise ValueError(
                    "rejected alternative cannot have an allowed PolicyResult"
                )
            explanations.append(
                RejectedCandidateExplanation(
                    candidate=candidate,
                    policy_violations=list(policy_result.violations),
                )
            )
        return explanations

    @staticmethod
    def _build_cognitive_trace(
        context: DecisionContext | None,
    ) -> CognitiveTrace | None:
        if context is None:
            return None
        return CognitiveTrace(
            evidence=[
                EvidenceTrace(
                    evidence_id=item.id,
                    evidence_type=item.evidence_type,
                    reliability=item.reliability,
                    freshness=item.freshness,
                    limitations=list(item.limitations),
                )
                for item in context.evidence
            ],
            claims=[
                ClaimTrace(
                    claim_id=item.id,
                    claim_type=item.claim_type,
                    status=item.status,
                    supporting_evidence_ids=list(item.supporting_evidence_ids),
                )
                for item in context.claims
            ],
            hypotheses=[
                HypothesisTrace(
                    hypothesis_id=item.id,
                    status=item.status,
                    supporting_evidence_ids=list(item.supporting_evidence_ids),
                    missing_evidence_ids=list(item.missing_evidence_ids),
                )
                for item in context.hypotheses
            ],
            context_freshness=context.freshness,
            miner_freshness=context.miner_freshness,
            hardware_freshness=context.hardware_freshness,
        )

    @staticmethod
    def _unique_limitations(
        limitations: Sequence[ExplanationLimitation],
    ) -> list[ExplanationLimitation]:
        return list(dict.fromkeys(limitations))
