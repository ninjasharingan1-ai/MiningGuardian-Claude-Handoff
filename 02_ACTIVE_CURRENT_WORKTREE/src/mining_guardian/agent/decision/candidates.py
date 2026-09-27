"""Deterministic candidate generation from validated cognitive context."""

from collections.abc import Iterable

from ..cognition.claims import Claim
from ..cognition.enums import ClaimStatus, HypothesisStatus
from ..cognition.evidence import EvidenceItem
from ..cognition.hypotheses import Hypothesis
from ..cognition.validation import validate_reasoning
from .context import DecisionContext
from .models import ActionType, CandidateAction, ExecutionCategory

_DECISION_DOMAIN_METADATA_KEY = "decision_domain"

_ACTION_BY_DOMAIN: dict[str, ActionType] = {
    "performance": ActionType.INVESTIGATE_PERFORMANCE,
    "efficiency": ActionType.EVALUATE_EFFICIENCY,
    "network": ActionType.EVALUATE_NETWORK,
}

_GENERATION_ORDER = (
    ActionType.NO_ACTION,
    ActionType.INVESTIGATE_PERFORMANCE,
    ActionType.EVALUATE_EFFICIENCY,
    ActionType.EVALUATE_NETWORK,
)

_DESCRIPTIONS: dict[ActionType, str] = {
    ActionType.NO_ACTION: "Preserve the current state; no supported candidate is required.",
    ActionType.INVESTIGATE_PERFORMANCE: "Investigate the supported performance condition.",
    ActionType.EVALUATE_EFFICIENCY: "Evaluate the supported efficiency condition.",
    ActionType.EVALUATE_NETWORK: "Evaluate the supported network condition.",
}


class CandidateGenerator:
    """Create bounded, non-executing candidates from supported cognitive chains."""

    def generate(self, context: DecisionContext) -> list[CandidateAction]:
        """Return a stable candidate set without ranking or operational inference."""

        supported_actions = self._supported_actions(context)
        return [
            self._candidate(action_type)
            for action_type in _GENERATION_ORDER
            if action_type is ActionType.NO_ACTION or action_type in supported_actions
        ]

    @staticmethod
    def _candidate(action_type: ActionType) -> CandidateAction:
        return CandidateAction(
            id=f"candidate-{action_type.value}",
            action_type=action_type,
            description=_DESCRIPTIONS[action_type],
            execution_category=ExecutionCategory.OBSERVATION_ONLY,
            expected_gain=0.0,
            confidence=0.0,
            risk_score=0.0,
            transition_cost=0.0,
            reversible=True,
        )

    def _supported_actions(self, context: DecisionContext) -> set[ActionType]:
        if not context.evidence or not context.claims or not context.hypotheses:
            return set()

        evidence_by_id = {item.id: item for item in context.evidence}
        supported_claims = self._supported_claims(context.evidence, context.claims)
        actions: set[ActionType] = set()

        for hypothesis in context.hypotheses:
            if not self._hypothesis_has_sufficient_support(hypothesis, evidence_by_id):
                continue

            hypothesis_evidence_ids = set(hypothesis.supporting_evidence_ids)
            for claim in supported_claims:
                shared_ids = hypothesis_evidence_ids.intersection(
                    claim.supporting_evidence_ids
                )
                actions.update(
                    self._actions_from_evidence(
                        evidence_by_id[evidence_id]
                        for evidence_id in sorted(shared_ids)
                    )
                )

        return actions

    @staticmethod
    def _supported_claims(
        evidence: list[EvidenceItem],
        claims: list[Claim],
    ) -> list[Claim]:
        supported: list[Claim] = []
        for claim in claims:
            if claim.status is not ClaimStatus.SUPPORTED:
                continue
            if not claim.supporting_evidence_ids:
                continue
            if validate_reasoning(evidence, [claim]).valid:
                supported.append(claim)
        return supported

    @staticmethod
    def _hypothesis_has_sufficient_support(
        hypothesis: Hypothesis,
        evidence_by_id: dict[str, EvidenceItem],
    ) -> bool:
        if hypothesis.status not in {
            HypothesisStatus.ACTIVE,
            HypothesisStatus.SUPPORTED,
        }:
            return False
        if not hypothesis.supporting_evidence_ids:
            return False
        if hypothesis.missing_evidence_ids:
            return False

        return set(hypothesis.supporting_evidence_ids) <= evidence_by_id.keys()

    @staticmethod
    def _actions_from_evidence(
        evidence_items: Iterable[EvidenceItem],
    ) -> set[ActionType]:
        actions: set[ActionType] = set()
        for evidence in evidence_items:
            domain = evidence.metadata.get(_DECISION_DOMAIN_METADATA_KEY)
            if isinstance(domain, str):
                action_type = _ACTION_BY_DOMAIN.get(domain)
                if action_type is not None:
                    actions.add(action_type)
        return actions
