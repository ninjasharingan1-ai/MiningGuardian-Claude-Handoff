import inspect

import pytest

import mining_guardian.agent.decision.ranking as ranking_module
from mining_guardian.agent.decision import (
    ActionType,
    CandidateAction,
    CandidateGenerator,
    DecisionContext,
    DecisionPolicy,
    DecisionRanker,
    DecisionResult,
    DecisionScore,
    DecisionScorer,
    ExecutionCategory,
    OutcomePredictor,
    PolicyResult,
    PredictionHorizon,
    PredictionResult,
    RankedCandidate,
)
from mining_guardian.agent.decision.lifecycle import DecisionState, can_transition


def _candidate(
    candidate_id: str,
    action_type: ActionType,
    *,
    reversible: bool = True,
) -> CandidateAction:
    return CandidateAction(
        id=candidate_id,
        action_type=action_type,
        description=f"Candidate {candidate_id}",
        execution_category=ExecutionCategory.OBSERVATION_ONLY,
        expected_gain=0.0,
        confidence=0.0,
        risk_score=0.0,
        transition_cost=0.0,
        reversible=reversible,
    )


def _score(
    candidate_id: str,
    *,
    utility_score: float,
    risk: float = 0.2,
    confidence: float = 0.8,
    action_cost: float = 0.1,
    benefit: float = 1.0,
    uncertainty: float = 0.1,
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


def _rank(
    pairs: list[tuple[CandidateAction, DecisionScore]],
) -> list[RankedCandidate]:
    return DecisionRanker().rank(
        [candidate for candidate, _ in pairs],
        [score for _, score in pairs],
    )


def test_valid_ranking_with_multiple_candidates():
    candidates = [
        _candidate("a", ActionType.NO_ACTION),
        _candidate("b", ActionType.INVESTIGATE_PERFORMANCE),
        _candidate("c", ActionType.EVALUATE_NETWORK),
    ]
    scores = [
        _score("a", utility_score=0.1),
        _score("b", utility_score=0.9),
        _score("c", utility_score=0.4),
    ]

    ranked = DecisionRanker().rank(candidates, scores)

    assert [item.candidate.id for item in ranked] == ["b", "c", "a"]
    assert [item.rank for item in ranked] == [1, 2, 3]


def test_higher_utility_score_ranks_first():
    ranked = _rank(
        [
            (
                _candidate("low", ActionType.EVALUATE_EFFICIENCY),
                _score("low", utility_score=0.2),
            ),
            (
                _candidate("high", ActionType.EVALUATE_NETWORK),
                _score("high", utility_score=0.8),
            ),
        ]
    )

    assert ranked[0].candidate.id == "high"


def test_negative_utility_scores_are_not_clamped():
    ranked = _rank(
        [
            (
                _candidate("worse", ActionType.EVALUATE_EFFICIENCY),
                _score("worse", utility_score=-2.0),
            ),
            (
                _candidate("better", ActionType.EVALUATE_NETWORK),
                _score("better", utility_score=-0.5),
            ),
        ]
    )

    assert [item.score.utility_score for item in ranked] == [-0.5, -2.0]


def test_equal_utility_lower_risk_ranks_first():
    ranked = _rank(
        [
            (
                _candidate("high-risk", ActionType.EVALUATE_NETWORK),
                _score("high-risk", utility_score=1.0, risk=0.4),
            ),
            (
                _candidate("low-risk", ActionType.EVALUATE_EFFICIENCY),
                _score("low-risk", utility_score=1.0, risk=0.1),
            ),
        ]
    )

    assert ranked[0].candidate.id == "low-risk"


def test_equal_utility_and_risk_higher_confidence_ranks_first():
    ranked = _rank(
        [
            (
                _candidate("low-confidence", ActionType.EVALUATE_NETWORK),
                _score(
                    "low-confidence",
                    utility_score=1.0,
                    risk=0.2,
                    confidence=0.4,
                ),
            ),
            (
                _candidate("high-confidence", ActionType.EVALUATE_EFFICIENCY),
                _score(
                    "high-confidence",
                    utility_score=1.0,
                    risk=0.2,
                    confidence=0.9,
                ),
            ),
        ]
    )

    assert ranked[0].candidate.id == "high-confidence"


def test_equal_utility_risk_confidence_lower_cost_ranks_first():
    ranked = _rank(
        [
            (
                _candidate("high-cost", ActionType.EVALUATE_NETWORK),
                _score(
                    "high-cost",
                    utility_score=1.0,
                    risk=0.2,
                    confidence=0.8,
                    action_cost=0.4,
                ),
            ),
            (
                _candidate("low-cost", ActionType.EVALUATE_EFFICIENCY),
                _score(
                    "low-cost",
                    utility_score=1.0,
                    risk=0.2,
                    confidence=0.8,
                    action_cost=0.1,
                ),
            ),
        ]
    )

    assert ranked[0].candidate.id == "low-cost"


def test_equal_meaningful_fields_reversible_candidate_ranks_first():
    ranked = _rank(
        [
            (
                _candidate(
                    "irreversible",
                    ActionType.EVALUATE_NETWORK,
                    reversible=False,
                ),
                _score("irreversible", utility_score=1.0),
            ),
            (
                _candidate(
                    "reversible",
                    ActionType.EVALUATE_EFFICIENCY,
                    reversible=True,
                ),
                _score("reversible", utility_score=1.0),
            ),
        ]
    )

    assert ranked[0].candidate.id == "reversible"


def test_perfect_tie_uses_action_type_declaration_order():
    ranked = _rank(
        [
            (
                _candidate("network", ActionType.EVALUATE_NETWORK),
                _score("network", utility_score=1.0),
            ),
            (
                _candidate("no-action", ActionType.NO_ACTION),
                _score("no-action", utility_score=1.0),
            ),
        ]
    )

    assert [item.candidate.action_type for item in ranked] == [
        ActionType.NO_ACTION,
        ActionType.EVALUATE_NETWORK,
    ]


def test_same_action_type_perfect_tie_uses_candidate_id():
    ranked = _rank(
        [
            (
                _candidate("zeta", ActionType.EVALUATE_NETWORK),
                _score("zeta", utility_score=1.0),
            ),
            (
                _candidate("alpha", ActionType.EVALUATE_NETWORK),
                _score("alpha", utility_score=1.0),
            ),
        ]
    )

    assert [item.candidate.id for item in ranked] == ["alpha", "zeta"]


def test_no_action_participates_normally():
    ranked = _rank(
        [
            (
                _candidate("hold", ActionType.NO_ACTION),
                _score("hold", utility_score=0.4),
            ),
            (
                _candidate("investigate", ActionType.INVESTIGATE_PERFORMANCE),
                _score("investigate", utility_score=0.3),
            ),
        ]
    )

    assert ranked[0].candidate.action_type is ActionType.NO_ACTION


def test_no_action_receives_no_hidden_bonus():
    ranked = _rank(
        [
            (
                _candidate("hold", ActionType.NO_ACTION),
                _score("hold", utility_score=0.1, risk=0.0, action_cost=0.0),
            ),
            (
                _candidate("evaluate", ActionType.EVALUATE_NETWORK),
                _score("evaluate", utility_score=0.2, risk=1.0, action_cost=1.0),
            ),
        ]
    )

    assert ranked[0].candidate.id == "evaluate"


def test_no_action_receives_no_hidden_penalty():
    ranked = _rank(
        [
            (
                _candidate("hold", ActionType.NO_ACTION),
                _score("hold", utility_score=0.2, risk=1.0, action_cost=1.0),
            ),
            (
                _candidate("evaluate", ActionType.EVALUATE_NETWORK),
                _score("evaluate", utility_score=0.1, risk=0.0, action_cost=0.0),
            ),
        ]
    )

    assert ranked[0].candidate.id == "hold"


def test_ranking_does_not_alter_utility_score():
    score = _score("candidate", utility_score=0.375)
    ranked = _rank(
        [(_candidate("candidate", ActionType.EVALUATE_EFFICIENCY), score)]
    )

    assert ranked[0].score.utility_score == 0.375
    assert ranked[0].score is score


def test_ranked_candidate_has_no_secondary_numeric_score():
    assert set(RankedCandidate.model_fields) == {"rank", "candidate", "score"}


def test_ranking_source_has_no_weighted_or_bonus_formula():
    source = inspect.getsource(ranking_module)

    assert "weighted_" not in source
    assert "bonus" not in source
    assert "penalty" not in source


def test_candidate_identity_remains_associated_with_its_score():
    first = _candidate("first", ActionType.INVESTIGATE_PERFORMANCE)
    second = _candidate("second", ActionType.EVALUATE_NETWORK)
    first_score = _score("first", utility_score=0.2)
    second_score = _score("second", utility_score=0.8)

    ranked = DecisionRanker().rank(
        [first, second],
        [second_score, first_score],
    )

    assert ranked[0].candidate is second
    assert ranked[0].score is second_score
    assert ranked[1].candidate is first
    assert ranked[1].score is first_score


def test_score_referencing_unknown_candidate_fails_safely():
    with pytest.raises(ValueError, match="unknown candidate"):
        DecisionRanker().rank(
            [_candidate("known", ActionType.NO_ACTION)],
            [
                _score("known", utility_score=0.0),
                _score("unknown", utility_score=1.0),
            ],
        )


def test_candidate_without_score_fails_safely():
    with pytest.raises(ValueError, match="missing DecisionScore"):
        DecisionRanker().rank(
            [
                _candidate("scored", ActionType.NO_ACTION),
                _candidate("missing", ActionType.EVALUATE_NETWORK),
            ],
            [_score("scored", utility_score=0.0)],
        )


def test_duplicate_candidate_id_fails_safely():
    with pytest.raises(ValueError, match="duplicate candidate id"):
        DecisionRanker().rank(
            [
                _candidate("duplicate", ActionType.NO_ACTION),
                _candidate("duplicate", ActionType.EVALUATE_NETWORK),
            ],
            [_score("duplicate", utility_score=0.0)],
        )


def test_duplicate_score_mapping_fails_safely():
    with pytest.raises(ValueError, match="duplicate DecisionScore"):
        DecisionRanker().rank(
            [_candidate("candidate", ActionType.NO_ACTION)],
            [
                _score("candidate", utility_score=0.0),
                _score("candidate", utility_score=0.1),
            ],
        )


def test_empty_input_returns_empty_ranking():
    assert DecisionRanker().rank([], []) == []


def test_same_input_produces_identical_ordering():
    candidates = [
        _candidate("c", ActionType.EVALUATE_NETWORK),
        _candidate("a", ActionType.NO_ACTION),
        _candidate("b", ActionType.EVALUATE_EFFICIENCY),
    ]
    scores = [
        _score("c", utility_score=0.4),
        _score("a", utility_score=0.4),
        _score("b", utility_score=0.4),
    ]
    ranker = DecisionRanker()

    first = ranker.rank(candidates, scores)
    second = ranker.rank(candidates, scores)

    assert first == second


def test_candidate_objects_are_not_mutated():
    candidate = _candidate("candidate", ActionType.EVALUATE_EFFICIENCY)
    before = candidate.model_dump()

    DecisionRanker().rank(
        [candidate],
        [_score("candidate", utility_score=1.0)],
    )

    assert candidate.model_dump() == before


def test_decision_score_objects_are_not_mutated():
    score = _score("candidate", utility_score=1.0)
    before = score.model_dump()

    DecisionRanker().rank(
        [_candidate("candidate", ActionType.EVALUATE_EFFICIENCY)],
        [score],
    )

    assert score.model_dump() == before


def test_scoring_separation_uses_precomputed_utility_before_tie_breakers():
    high_utility = _candidate(
        "high-utility",
        ActionType.EVALUATE_NETWORK,
        reversible=False,
    )
    lower_utility = _candidate(
        "lower-utility",
        ActionType.NO_ACTION,
        reversible=True,
    )
    ranked = DecisionRanker().rank(
        [high_utility, lower_utility],
        [
            _score(
                "high-utility",
                utility_score=0.500001,
                risk=1.0,
                confidence=0.0,
                action_cost=1.0,
            ),
            _score(
                "lower-utility",
                utility_score=0.5,
                risk=0.0,
                confidence=1.0,
                action_cost=0.0,
            ),
        ],
    )

    assert ranked[0].candidate.id == "high-utility"
    assert ranked[0].score.utility_score == 0.500001


def test_phase_one_contracts_remain_compatible():
    candidate = _candidate("phase-one", ActionType.NO_ACTION)
    result = DecisionResult(
        decision_id="decision",
        state="proposed",
        selected_action=candidate,
        explanation="Compatible",
    )

    assert result.selected_action == candidate
    assert candidate.execution_category is ExecutionCategory.OBSERVATION_ONLY


def test_phase_two_lifecycle_remains_compatible():
    assert can_transition(DecisionState.DETECTED, DecisionState.ANALYZING)


def test_phase_three_decision_context_remains_compatible():
    context = DecisionContext()

    assert context.evidence == []
    assert context.claims == []
    assert context.hypotheses == []


def test_phase_four_candidate_generator_remains_compatible():
    candidates = CandidateGenerator().generate(DecisionContext())

    assert [candidate.action_type for candidate in candidates] == [
        ActionType.NO_ACTION
    ]


def test_phase_five_policy_contracts_remain_compatible():
    policy = DecisionPolicy(
        minimum_confidence=0.0,
        maximum_risk=1.0,
        minimum_expected_gain=0.0,
        allowed_execution_categories=[ExecutionCategory.OBSERVATION_ONLY],
        required_evidence_types=[],
    )
    result = PolicyResult(allowed=True, violations=[])

    assert policy.minimum_confidence == 0.0
    assert result.allowed


def test_phase_six_prediction_contracts_remain_compatible():
    prediction = PredictionResult(
        candidate_id="candidate",
        confidence=0.8,
        uncertainty=0.1,
        horizon=PredictionHorizon.SHORT_TERM,
    )

    assert prediction.candidate_id == "candidate"
    assert OutcomePredictor is not None


def test_phase_seven_scoring_contracts_remain_compatible():
    candidate = _candidate("candidate", ActionType.EVALUATE_NETWORK)
    prediction = PredictionResult(
        candidate_id="candidate",
        expected_reward_change=2.0,
        confidence=0.5,
        uncertainty=0.1,
        horizon=PredictionHorizon.IMMEDIATE,
    )

    score = DecisionScorer().score(candidate, prediction)

    assert isinstance(score, DecisionScore)
    assert score.candidate_id == candidate.id


def test_phase_eight_introduces_no_execution_or_external_io_surface():
    source = inspect.getsource(ranking_module)

    forbidden = (
        "subprocess",
        "requests",
        "httpx",
        "pynvml",
        "srbminer",
        "execute(",
        "apply(",
        "control(",
    )
    assert all(token not in source.lower() for token in forbidden)
