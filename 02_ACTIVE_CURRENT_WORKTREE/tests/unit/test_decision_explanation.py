import inspect

import pytest

import mining_guardian.agent.decision.explanation as explanation_module
from mining_guardian.agent.cognition.claims import Claim
from mining_guardian.agent.cognition.enums import (
    ClaimStatus,
    ClaimType,
    Confidence,
    EvidenceType,
    HypothesisStatus,
    Reliability,
)
from mining_guardian.agent.cognition.evidence import EvidenceItem
from mining_guardian.agent.cognition.hypotheses import Hypothesis
from mining_guardian.agent.decision import (
    ActionType,
    CandidateAction,
    CandidateExplanation,
    CandidateGenerator,
    ConfidenceLimitation,
    DecisionConfidenceEngine,
    DecisionConfidenceResult,
    DecisionContext,
    DecisionEngine,
    DecisionExplainer,
    DecisionExplanation,
    DecisionPolicy,
    DecisionRanker,
    DecisionResult,
    DecisionScore,
    DecisionScorer,
    EvidenceConfidenceInput,
    ExecutionCategory,
    ExplanationLimitation,
    OutcomePredictor,
    PolicyResult,
    PredictionHorizon,
    PredictionResult,
    RankedCandidate,
)
from mining_guardian.agent.decision.lifecycle import DecisionState, can_transition
from mining_guardian.agent.temporal import FreshnessLevel


def _candidate(
    candidate_id: str,
    action_type: ActionType,
    *,
    description: str | None = None,
) -> CandidateAction:
    return CandidateAction(
        id=candidate_id,
        action_type=action_type,
        description=description or f"Candidate {candidate_id}",
        execution_category=ExecutionCategory.OBSERVATION_ONLY,
        expected_gain=0.0,
        confidence=0.0,
        risk_score=0.0,
        transition_cost=0.0,
        reversible=True,
    )


def _score(
    candidate_id: str,
    *,
    utility_score: float,
    benefit: float = 0.4,
    confidence: float = 0.8,
    risk: float = 0.1,
    action_cost: float = 0.05,
    uncertainty: float = 0.2,
) -> DecisionScore:
    return DecisionScore(
        candidate_id=candidate_id,
        benefit=benefit,
        confidence=confidence,
        risk=risk,
        action_cost=action_cost,
        uncertainty=uncertainty,
        utility_score=utility_score,
    )


def _ranked(
    candidate: CandidateAction,
    score: DecisionScore,
    rank: int,
) -> RankedCandidate:
    return RankedCandidate(rank=rank, candidate=candidate, score=score)


def _result(
    *,
    selected: CandidateAction | None,
    alternatives: list[CandidateAction] | None = None,
    rejected: list[CandidateAction] | None = None,
) -> DecisionResult:
    return DecisionResult(
        decision_id="decision-1",
        state=DecisionState.APPROVED.value if selected else DecisionState.REJECTED.value,
        selected_action=selected,
        alternatives=alternatives or [],
        rejected_alternatives=rejected or [],
        confidence=0.7 if selected else 0.0,
        explanation="phase-10-summary",
    )


def _evidence() -> EvidenceItem:
    return EvidenceItem(
        id="evidence-1",
        evidence_type=EvidenceType.MEASURED,
        source="test",
        value={"raw_metric": 42},
        freshness=FreshnessLevel.RECENT,
        reliability=Reliability.HIGH,
        limitations=["measurement_window_limited"],
        metadata={"decision_domain": "performance"},
    )


def _claim() -> Claim:
    return Claim(
        id="claim-1",
        statement="Performance degradation is supported.",
        claim_type=ClaimType.OBSERVATION,
        supporting_evidence_ids=["evidence-1"],
        confidence=Confidence.HIGH,
        status=ClaimStatus.SUPPORTED,
    )


def _hypothesis() -> Hypothesis:
    return Hypothesis(
        id="hypothesis-1",
        statement="Investigate performance conditions.",
        supporting_evidence_ids=["evidence-1"],
        confidence=Confidence.MEDIUM,
        status=HypothesisStatus.ACTIVE,
    )


def _context() -> DecisionContext:
    return DecisionContext(
        evidence=[_evidence()],
        claims=[_claim()],
        hypotheses=[_hypothesis()],
        freshness=FreshnessLevel.RECENT,
        miner_freshness=FreshnessLevel.FRESH,
        hardware_freshness=FreshnessLevel.RECENT,
    )


def _confidence(candidate_id: str) -> DecisionConfidenceResult:
    return DecisionConfidenceResult(
        candidate_id=candidate_id,
        evidence_inputs=[
            EvidenceConfidenceInput(
                evidence_id="evidence-1",
                reliability=Reliability.HIGH,
                freshness=FreshnessLevel.RECENT,
            )
        ],
        context_freshness=FreshnessLevel.RECENT,
        miner_freshness=FreshnessLevel.FRESH,
        hardware_freshness=FreshnessLevel.RECENT,
        prediction_reliability=0.73,
        overall_confidence=None,
        limitations=[
            ConfidenceLimitation.NUMERIC_EVIDENCE_QUALITY_UNAVAILABLE,
            ConfidenceLimitation.NUMERIC_FRESHNESS_FACTOR_UNAVAILABLE,
        ],
    )


def test_decision_explanation_valid_construction():
    selected = _candidate("selected", ActionType.INVESTIGATE_PERFORMANCE)
    score = _score("selected", utility_score=0.42)

    explanation = DecisionExplanation(
        decision_id="decision-1",
        decision_state=DecisionState.APPROVED.value,
        selected=CandidateExplanation(
            rank=1,
            candidate=selected,
            score=score,
            reason="highest_ranked_eligible_candidate",
        ),
    )

    assert explanation.selected is not None
    assert explanation.selected.candidate is selected
    assert explanation.selected.score is score


def test_decision_explanation_serialization_round_trip():
    selected = _candidate("selected", ActionType.INVESTIGATE_PERFORMANCE)
    ranking = [_ranked(selected, _score("selected", utility_score=0.42), 1)]
    explanation = DecisionExplainer().explain(
        _result(selected=selected),
        ranking=ranking,
        confidence=_confidence("selected"),
        context=_context(),
    )

    restored = DecisionExplanation.model_validate_json(explanation.model_dump_json())

    assert restored == explanation


def test_selected_candidate_identity_and_action_type_are_preserved():
    selected = _candidate("selected", ActionType.EVALUATE_NETWORK)
    ranking = [_ranked(selected, _score("selected", utility_score=0.6), 1)]

    explanation = DecisionExplainer().explain(
        _result(selected=selected),
        ranking=ranking,
    )

    assert explanation.selected is not None
    assert explanation.selected.candidate.id == "selected"
    assert explanation.selected.candidate.action_type is ActionType.EVALUATE_NETWORK


def test_selected_score_and_all_components_are_preserved_exactly():
    selected = _candidate("selected", ActionType.EVALUATE_EFFICIENCY)
    score = _score(
        "selected",
        utility_score=-3.14159,
        benefit=9.0,
        confidence=0.31,
        risk=0.7,
        action_cost=1.25,
        uncertainty=0.44,
    )

    explanation = DecisionExplainer().explain(
        _result(selected=selected),
        ranking=[_ranked(selected, score, 1)],
    )

    assert explanation.selected is not None
    assert explanation.selected.score is score
    assert explanation.selected.score.utility_score == -3.14159
    assert explanation.selected.score.benefit == 9.0
    assert explanation.selected.score.confidence == 0.31
    assert explanation.selected.score.risk == 0.7
    assert explanation.selected.score.action_cost == 1.25
    assert explanation.selected.score.uncertainty == 0.44


def test_scoring_separation_preserves_authoritative_utility_even_if_inconsistent():
    selected = _candidate("selected", ActionType.INVESTIGATE_PERFORMANCE)
    # Deliberately does not equal the ADR equation for these components.
    score = _score(
        "selected",
        utility_score=99.123,
        benefit=1.0,
        confidence=0.5,
        risk=0.1,
        action_cost=0.1,
        uncertainty=0.1,
    )

    explanation = DecisionExplainer().explain(
        _result(selected=selected),
        ranking=[_ranked(selected, score, 1)],
    )

    assert explanation.selected is not None
    assert explanation.selected.score.utility_score == 99.123
    assert set(CandidateExplanation.model_fields) == {
        "rank",
        "candidate",
        "score",
        "reason",
    }


def test_eligible_alternatives_are_separate_from_rejected_alternatives():
    selected = _candidate("a", ActionType.NO_ACTION)
    alternative = _candidate("b", ActionType.EVALUATE_NETWORK)
    rejected = _candidate("c", ActionType.EVALUATE_EFFICIENCY)
    ranking = [
        _ranked(selected, _score("a", utility_score=0.4), 1),
        _ranked(alternative, _score("b", utility_score=0.3), 2),
    ]

    explanation = DecisionExplainer().explain(
        _result(
            selected=selected,
            alternatives=[alternative],
            rejected=[rejected],
        ),
        ranking=ranking,
        policy_results={
            "c": PolicyResult(
                allowed=False,
                violations=["confidence_below_minimum"],
            )
        },
    )

    assert [item.candidate.id for item in explanation.alternatives] == ["b"]
    assert [item.candidate.id for item in explanation.rejected_alternatives] == ["c"]


def test_policy_violations_are_preserved_exactly_when_available():
    selected = _candidate("a", ActionType.NO_ACTION)
    rejected = _candidate("c", ActionType.EVALUATE_NETWORK)
    violations = ["risk_above_maximum", "required_evidence_missing"]

    explanation = DecisionExplainer().explain(
        _result(selected=selected, rejected=[rejected]),
        ranking=[_ranked(selected, _score("a", utility_score=0.1), 1)],
        policy_results={
            "c": PolicyResult(allowed=False, violations=violations)
        },
    )

    assert explanation.rejected_alternatives[0].policy_violations == violations
    assert explanation.rejected_alternatives[0].limitations == []


def test_missing_rejection_reason_is_explicit_and_not_fabricated():
    selected = _candidate("a", ActionType.NO_ACTION)
    rejected = _candidate("c", ActionType.EVALUATE_NETWORK)

    explanation = DecisionExplainer().explain(
        _result(selected=selected, rejected=[rejected]),
        ranking=[_ranked(selected, _score("a", utility_score=0.1), 1)],
    )

    rejected_explanation = explanation.rejected_alternatives[0]
    assert rejected_explanation.policy_violations == []
    assert rejected_explanation.limitations == [
        ExplanationLimitation.REJECTION_REASON_UNAVAILABLE
    ]
    serialized = rejected_explanation.model_dump_json()
    assert "confidence_below_minimum" not in serialized
    assert "risk_above_maximum" not in serialized
    assert "expected_gain_below_minimum" not in serialized
    assert "required_evidence_missing" not in serialized


def test_confidence_result_is_preserved_without_new_aggregate():
    selected = _candidate("a", ActionType.NO_ACTION)
    confidence = _confidence("a")

    explanation = DecisionExplainer().explain(
        _result(selected=selected),
        ranking=[_ranked(selected, _score("a", utility_score=0.1), 1)],
        confidence=confidence,
    )

    assert explanation.confidence is confidence
    assert explanation.confidence.overall_confidence is None
    assert ExplanationLimitation.AGGREGATE_CONFIDENCE_UNAVAILABLE in (
        explanation.limitations
    )


def test_confidence_candidate_identity_mismatch_fails_safely():
    selected = _candidate("a", ActionType.NO_ACTION)

    with pytest.raises(ValueError, match="confidence candidate_id"):
        DecisionExplainer().explain(
            _result(selected=selected),
            ranking=[_ranked(selected, _score("a", utility_score=0.1), 1)],
            confidence=_confidence("different"),
        )


def test_context_evidence_claim_hypothesis_traceability_is_preserved():
    selected = _candidate("a", ActionType.INVESTIGATE_PERFORMANCE)

    explanation = DecisionExplainer().explain(
        _result(selected=selected),
        ranking=[_ranked(selected, _score("a", utility_score=0.2), 1)],
        context=_context(),
    )

    trace = explanation.cognitive_trace
    assert trace is not None
    assert trace.evidence[0].evidence_id == "evidence-1"
    assert trace.evidence[0].evidence_type is EvidenceType.MEASURED
    assert trace.evidence[0].reliability is Reliability.HIGH
    assert trace.evidence[0].freshness is FreshnessLevel.RECENT
    assert trace.claims[0].claim_id == "claim-1"
    assert trace.claims[0].status is ClaimStatus.SUPPORTED
    assert trace.hypotheses[0].hypothesis_id == "hypothesis-1"
    assert trace.hypotheses[0].status is HypothesisStatus.ACTIVE


def test_cognitive_trace_does_not_dump_raw_evidence_value_payload():
    assert "value" not in explanation_module.EvidenceTrace.model_fields


def test_context_level_provenance_limitation_is_explicit():
    selected = _candidate("a", ActionType.INVESTIGATE_PERFORMANCE)

    explanation = DecisionExplainer().explain(
        _result(selected=selected),
        ranking=[_ranked(selected, _score("a", utility_score=0.2), 1)],
        context=_context(),
    )

    assert ExplanationLimitation.CANDIDATE_PROVENANCE_INCOMPLETE in (
        explanation.limitations
    )


def test_no_action_receives_only_rank_artifact_reason_not_safety_narrative():
    selected = _candidate("hold", ActionType.NO_ACTION)
    explanation = DecisionExplainer().explain(
        _result(selected=selected),
        ranking=[_ranked(selected, _score("hold", utility_score=0.5), 1)],
    )

    assert explanation.selected is not None
    assert explanation.selected.reason == "highest_ranked_eligible_candidate"
    rendered = explanation.render_text().lower()
    assert "safest" not in rendered
    assert "bonus" not in rendered
    assert "penalty" not in rendered


def test_all_rejected_no_selection_is_explained_without_fabrication():
    rejected = _candidate("rejected", ActionType.EVALUATE_NETWORK)
    result = _result(selected=None, rejected=[rejected])

    explanation = DecisionExplainer().explain(
        result,
        ranking=[],
        policy_results={
            "rejected": PolicyResult(
                allowed=False,
                violations=["execution_category_not_allowed"],
            )
        },
    )

    assert explanation.selected is None
    assert explanation.alternatives == []
    assert explanation.rejected_alternatives[0].candidate.id == "rejected"
    assert ExplanationLimitation.NO_SELECTED_ACTION in explanation.limitations


def test_selected_action_without_ranking_keeps_identity_and_marks_score_unavailable():
    selected = _candidate("selected", ActionType.NO_ACTION)

    explanation = DecisionExplainer().explain(
        _result(selected=selected),
        ranking=[],
    )

    assert explanation.selected is not None
    assert explanation.selected.candidate is selected
    assert explanation.selected.score is None
    assert explanation.selected.rank is None
    assert ExplanationLimitation.SELECTED_SCORE_UNAVAILABLE in explanation.limitations


def test_selected_candidate_must_be_rank_one_when_ranking_is_supplied():
    selected = _candidate("selected", ActionType.NO_ACTION)

    with pytest.raises(ValueError, match="rank 1"):
        DecisionExplainer().explain(
            _result(selected=selected),
            ranking=[_ranked(selected, _score("selected", utility_score=0.1), 2)],
        )


def test_alternative_missing_ranking_artifact_fails_safely():
    selected = _candidate("a", ActionType.NO_ACTION)
    alternative = _candidate("b", ActionType.EVALUATE_NETWORK)

    with pytest.raises(ValueError, match="missing ranking artifact"):
        DecisionExplainer().explain(
            _result(selected=selected, alternatives=[alternative]),
            ranking=[_ranked(selected, _score("a", utility_score=0.1), 1)],
        )


def test_rejected_candidate_cannot_have_allowed_policy_result():
    selected = _candidate("a", ActionType.NO_ACTION)
    rejected = _candidate("b", ActionType.EVALUATE_NETWORK)

    with pytest.raises(ValueError, match="allowed PolicyResult"):
        DecisionExplainer().explain(
            _result(selected=selected, rejected=[rejected]),
            ranking=[_ranked(selected, _score("a", utility_score=0.1), 1)],
            policy_results={
                "b": PolicyResult(allowed=True, violations=[])
            },
        )


def test_duplicate_ranked_candidate_identity_fails_safely():
    candidate = _candidate("same", ActionType.NO_ACTION)

    with pytest.raises(ValueError, match="duplicate ranked candidate"):
        DecisionExplainer().explain(
            _result(selected=candidate),
            ranking=[
                _ranked(candidate, _score("same", utility_score=0.2), 1),
                _ranked(candidate, _score("same", utility_score=0.1), 2),
            ],
        )


def test_duplicate_rank_positions_fail_safely():
    selected = _candidate("a", ActionType.NO_ACTION)
    alternative = _candidate("b", ActionType.EVALUATE_NETWORK)

    with pytest.raises(ValueError, match="duplicate ranking position"):
        DecisionExplainer().explain(
            _result(selected=selected, alternatives=[alternative]),
            ranking=[
                _ranked(selected, _score("a", utility_score=0.2), 1),
                _ranked(alternative, _score("b", utility_score=0.1), 1),
            ],
        )


def test_ranked_score_identity_mismatch_fails_safely():
    selected = _candidate("a", ActionType.NO_ACTION)

    with pytest.raises(ValueError, match="DecisionScore candidate_id"):
        DecisionExplainer().explain(
            _result(selected=selected),
            ranking=[
                _ranked(selected, _score("different", utility_score=0.2), 1)
            ],
        )


def test_ranking_separation_preserves_explicit_order():
    selected = _candidate("a", ActionType.NO_ACTION)
    second = _candidate("b", ActionType.EVALUATE_NETWORK)
    third = _candidate("c", ActionType.EVALUATE_EFFICIENCY)
    ranking = [
        _ranked(selected, _score("a", utility_score=-10.0), 1),
        _ranked(second, _score("b", utility_score=100.0), 2),
        _ranked(third, _score("c", utility_score=50.0), 3),
    ]

    explanation = DecisionExplainer().explain(
        _result(selected=selected, alternatives=[second, third]),
        ranking=ranking,
    )

    assert explanation.selected is not None
    assert explanation.selected.candidate.id == "a"
    assert [item.candidate.id for item in explanation.alternatives] == ["b", "c"]
    assert [item.rank for item in explanation.alternatives] == [2, 3]


def test_same_inputs_produce_identical_explanation_and_text():
    selected = _candidate("a", ActionType.NO_ACTION)
    result = _result(selected=selected)
    ranking = [_ranked(selected, _score("a", utility_score=0.2), 1)]
    confidence = _confidence("a")
    context = _context()
    explainer = DecisionExplainer()

    first = explainer.explain(
        result,
        ranking=ranking,
        confidence=confidence,
        context=context,
    )
    second = explainer.explain(
        result,
        ranking=ranking,
        confidence=confidence,
        context=context,
    )

    assert first == second
    assert first.render_text() == second.render_text()


def test_explanation_does_not_mutate_supplied_artifacts():
    selected = _candidate("a", ActionType.NO_ACTION)
    alternative = _candidate("b", ActionType.EVALUATE_NETWORK)
    rejected = _candidate("c", ActionType.EVALUATE_EFFICIENCY)
    selected_score = _score("a", utility_score=0.2)
    alternative_score = _score("b", utility_score=0.1)
    ranking = [
        _ranked(selected, selected_score, 1),
        _ranked(alternative, alternative_score, 2),
    ]
    policy_result = PolicyResult(
        allowed=False,
        violations=["required_evidence_missing"],
    )
    context = _context()
    confidence = _confidence("a")
    result = _result(
        selected=selected,
        alternatives=[alternative],
        rejected=[rejected],
    )

    before = {
        "result": result.model_dump(),
        "selected": selected.model_dump(),
        "alternative": alternative.model_dump(),
        "rejected": rejected.model_dump(),
        "score": selected_score.model_dump(),
        "ranking": [item.model_dump() for item in ranking],
        "policy": policy_result.model_dump(),
        "context": context.model_dump(),
        "confidence": confidence.model_dump(),
        "evidence": context.evidence[0].model_dump(),
        "claim": context.claims[0].model_dump(),
        "hypothesis": context.hypotheses[0].model_dump(),
    }

    DecisionExplainer().explain(
        result,
        ranking=ranking,
        confidence=confidence,
        policy_results={"c": policy_result},
        context=context,
    )

    assert result.model_dump() == before["result"]
    assert selected.model_dump() == before["selected"]
    assert alternative.model_dump() == before["alternative"]
    assert rejected.model_dump() == before["rejected"]
    assert selected_score.model_dump() == before["score"]
    assert [item.model_dump() for item in ranking] == before["ranking"]
    assert policy_result.model_dump() == before["policy"]
    assert context.model_dump() == before["context"]
    assert confidence.model_dump() == before["confidence"]
    assert context.evidence[0].model_dump() == before["evidence"]
    assert context.claims[0].model_dump() == before["claim"]
    assert context.hypotheses[0].model_dump() == before["hypothesis"]


def test_prediction_result_is_not_needed_or_mutated_by_explanation_boundary():
    prediction = PredictionResult(
        candidate_id="a",
        expected_reward_change=0.2,
        confidence=0.8,
        uncertainty=0.1,
        horizon=PredictionHorizon.SHORT_TERM,
    )
    before = prediction.model_dump()
    selected = _candidate("a", ActionType.NO_ACTION)

    DecisionExplainer().explain(
        _result(selected=selected),
        ranking=[_ranked(selected, _score("a", utility_score=0.2), 1)],
    )

    assert prediction.model_dump() == before


def test_phase_1_through_10_public_contracts_remain_compatible():
    assert ActionType.NO_ACTION.value == "no_action"
    assert ExecutionCategory.FUTURE_CONTROL.value == "future_control"
    assert DecisionResult.model_fields["selected_action"]
    assert can_transition(DecisionState.DETECTED, DecisionState.ANALYZING)
    assert DecisionContext
    assert CandidateGenerator
    assert DecisionPolicy
    assert PolicyResult
    assert OutcomePredictor
    assert PredictionResult
    assert DecisionScorer
    assert DecisionScore
    assert DecisionRanker
    assert RankedCandidate
    assert DecisionConfidenceEngine
    assert DecisionConfidenceResult
    assert DecisionEngine


def test_explanation_source_does_not_contain_new_scoring_or_ranking_engine_logic():
    source = inspect.getsource(explanation_module)

    assert "DecisionScorer(" not in source
    assert "DecisionRanker(" not in source
    assert "DecisionConfidenceEngine(" not in source
    assert "utility_score =" not in source
    assert "sorted(" not in source


def test_explanation_source_has_no_chain_of_thought_or_external_inference_surface():
    source = inspect.getsource(explanation_module).lower()

    assert "scratchpad" not in source
    assert "chain_of_thought" not in source
    assert "openai" not in source
    assert "anthropic" not in source
    assert "subprocess" not in source
    assert "requests" not in source


def test_explanation_source_has_no_execution_or_control_surface():
    source = inspect.getsource(explanation_module).lower()

    forbidden = [
        "miner_restart",
        "pool_switch",
        "algorithm_switch",
        "nvml",
        "srbminer",
        "shell",
        "wallet",
    ]
    assert all(token not in source for token in forbidden)


def test_selected_candidate_cannot_also_be_rejected():
    selected = _candidate("same", ActionType.NO_ACTION)

    with pytest.raises(ValueError, match="selected candidate cannot also appear in rejected"):
        DecisionExplainer().explain(
            _result(selected=selected, rejected=[selected]),
            ranking=[_ranked(selected, _score("same", utility_score=0.2), 1)],
        )


def test_candidate_cannot_be_both_eligible_and_rejected_alternative():
    selected = _candidate("selected", ActionType.NO_ACTION)
    contradictory = _candidate("same", ActionType.EVALUATE_NETWORK)

    with pytest.raises(ValueError, match="both eligible and rejected"):
        DecisionExplainer().explain(
            _result(
                selected=selected,
                alternatives=[contradictory],
                rejected=[contradictory],
            ),
            ranking=[
                _ranked(selected, _score("selected", utility_score=0.2), 1),
                _ranked(contradictory, _score("same", utility_score=0.1), 2),
            ],
        )


def test_ranking_cannot_contain_candidate_absent_from_decision_result():
    selected = _candidate("selected", ActionType.NO_ACTION)
    extra = _candidate("extra", ActionType.EVALUATE_NETWORK)

    with pytest.raises(ValueError, match="exactly match DecisionResult eligible candidates"):
        DecisionExplainer().explain(
            _result(selected=selected),
            ranking=[
                _ranked(selected, _score("selected", utility_score=0.2), 1),
                _ranked(extra, _score("extra", utility_score=0.1), 2),
            ],
        )


def test_partial_ranking_cannot_omit_selected_candidate():
    selected = _candidate("selected", ActionType.NO_ACTION)
    alternative = _candidate("alternative", ActionType.EVALUATE_NETWORK)

    with pytest.raises(ValueError, match="exactly match DecisionResult eligible candidates"):
        DecisionExplainer().explain(
            _result(selected=selected, alternatives=[alternative]),
            ranking=[
                _ranked(alternative, _score("alternative", utility_score=0.1), 1)
            ],
        )


def test_ranking_positions_must_be_contiguous():
    selected = _candidate("selected", ActionType.NO_ACTION)
    alternative = _candidate("alternative", ActionType.EVALUATE_NETWORK)

    with pytest.raises(ValueError, match="contiguous starting at 1"):
        DecisionExplainer().explain(
            _result(selected=selected, alternatives=[alternative]),
            ranking=[
                _ranked(selected, _score("selected", utility_score=0.2), 1),
                _ranked(alternative, _score("alternative", utility_score=0.1), 3),
            ],
        )


def test_eligible_candidate_cannot_have_rejected_policy_result():
    selected = _candidate("selected", ActionType.NO_ACTION)

    with pytest.raises(ValueError, match="eligible candidate cannot have a rejected"):
        DecisionExplainer().explain(
            _result(selected=selected),
            ranking=[_ranked(selected, _score("selected", utility_score=0.2), 1)],
            policy_results={
                "selected": PolicyResult(
                    allowed=False,
                    violations=["confidence_below_minimum"],
                )
            },
        )


def test_policy_result_cannot_reference_unknown_candidate():
    selected = _candidate("selected", ActionType.NO_ACTION)

    with pytest.raises(ValueError, match="unknown DecisionResult candidate"):
        DecisionExplainer().explain(
            _result(selected=selected),
            ranking=[_ranked(selected, _score("selected", utility_score=0.2), 1)],
            policy_results={
                "ghost": PolicyResult(allowed=True, violations=[]),
            },
        )


def test_policy_result_allowed_state_and_violations_must_be_consistent():
    selected = _candidate("selected", ActionType.NO_ACTION)

    with pytest.raises(ValueError, match="allowed PolicyResult cannot contain"):
        DecisionExplainer().explain(
            _result(selected=selected),
            ranking=[_ranked(selected, _score("selected", utility_score=0.2), 1)],
            policy_results={
                "selected": PolicyResult(
                    allowed=True,
                    violations=["impossible_violation"],
                )
            },
        )


def test_confidence_artifact_requires_selected_candidate():
    rejected = _candidate("rejected", ActionType.EVALUATE_NETWORK)

    with pytest.raises(ValueError, match="confidence artifact requires a selected"):
        DecisionExplainer().explain(
            _result(selected=None, rejected=[rejected]),
            policy_results={
                "rejected": PolicyResult(
                    allowed=False,
                    violations=["required_evidence_missing"],
                )
            },
            confidence=_confidence("rejected"),
        )
