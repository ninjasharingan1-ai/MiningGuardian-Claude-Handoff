from copy import deepcopy

import pytest

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
    CandidateGenerator,
    ConfidenceLimitation,
    DecisionConfidenceEngine,
    DecisionConfidenceResult,
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
from mining_guardian.agent.decision.engine import (
    DecisionEngine,
    NoAdmissibleCandidateError,
)
from mining_guardian.agent.decision.lifecycle import DecisionState, can_transition
from mining_guardian.agent.temporal import FreshnessLevel


def _candidate(
    candidate_id: str,
    action_type: ActionType,
    *,
    expected_gain: float = 0.0,
    confidence: float = 0.0,
    risk_score: float = 0.0,
    transition_cost: float = 0.0,
    reversible: bool = True,
) -> CandidateAction:
    return CandidateAction(
        id=candidate_id,
        action_type=action_type,
        description=f"Candidate {candidate_id}",
        execution_category=ExecutionCategory.OBSERVATION_ONLY,
        expected_gain=expected_gain,
        confidence=confidence,
        risk_score=risk_score,
        transition_cost=transition_cost,
        reversible=reversible,
    )


def _prediction(
    candidate: CandidateAction,
    *,
    expected_reward_change: float | None = None,
    confidence: float = 0.8,
    uncertainty: float = 0.1,
) -> PredictionResult:
    return PredictionResult(
        candidate_id=candidate.id,
        expected_reward_change=expected_reward_change,
        expected_hashrate_change=None,
        expected_power_change=None,
        confidence=confidence,
        uncertainty=uncertainty,
        horizon=PredictionHorizon.SHORT_TERM,
        rationale="Deterministic test predictor.",
    )


def _score(
    candidate: CandidateAction,
    *,
    utility_score: float,
    confidence: float = 0.8,
) -> DecisionScore:
    return DecisionScore(
        candidate_id=candidate.id,
        benefit=0.0,
        confidence=confidence,
        risk=candidate.risk_score,
        action_cost=candidate.transition_cost,
        uncertainty=0.1,
        utility_score=utility_score,
    )


def _confidence(
    candidate_id: str,
    *,
    prediction_reliability: float = 0.8,
    overall_confidence: float | None = None,
) -> DecisionConfidenceResult:
    return DecisionConfidenceResult(
        candidate_id=candidate_id,
        context_freshness=FreshnessLevel.FRESH,
        miner_freshness=FreshnessLevel.FRESH,
        hardware_freshness=FreshnessLevel.FRESH,
        prediction_reliability=prediction_reliability,
        overall_confidence=overall_confidence,
        limitations=[
            ConfidenceLimitation.NUMERIC_EVIDENCE_QUALITY_UNAVAILABLE,
            ConfidenceLimitation.NUMERIC_FRESHNESS_FACTOR_UNAVAILABLE,
        ],
    )


def _policy() -> DecisionPolicy:
    return DecisionPolicy(
        minimum_confidence=0.0,
        maximum_risk=1.0,
        minimum_expected_gain=0.0,
        allowed_execution_categories=[ExecutionCategory.OBSERVATION_ONLY],
        required_evidence_types=[],
    )


def _context() -> DecisionContext:
    return DecisionContext(
        freshness=FreshnessLevel.FRESH,
        miner_freshness=FreshnessLevel.FRESH,
        hardware_freshness=FreshnessLevel.FRESH,
        decision_constraints=["read_only"],
    )


def _cognitive_context() -> DecisionContext:
    evidence = EvidenceItem(
        id="evidence-1",
        evidence_type=EvidenceType.MEASURED,
        source="test",
        value={"signal": "validated"},
        freshness=FreshnessLevel.FRESH,
        reliability=Reliability.HIGH,
        metadata={"decision_domain": "performance"},
    )
    claim = Claim(
        id="claim-1",
        statement="A performance condition is supported.",
        claim_type=ClaimType.OBSERVATION,
        supporting_evidence_ids=[evidence.id],
        confidence=Confidence.HIGH,
        status=ClaimStatus.SUPPORTED,
    )
    hypothesis = Hypothesis(
        id="hypothesis-1",
        statement="The supported condition warrants investigation.",
        supporting_evidence_ids=[evidence.id],
        confidence=Confidence.MEDIUM,
        status=HypothesisStatus.SUPPORTED,
    )
    return DecisionContext(
        evidence=[evidence],
        claims=[claim],
        hypotheses=[hypothesis],
        freshness=FreshnessLevel.FRESH,
        miner_freshness=FreshnessLevel.FRESH,
        hardware_freshness=FreshnessLevel.FRESH,
        decision_constraints=["read_only"],
    )


class StubGenerator:
    def __init__(self, candidates: list[CandidateAction], events: list[str] | None = None):
        self.candidates = candidates
        self.events = events

    def generate(self, context: DecisionContext) -> list[CandidateAction]:
        if self.events is not None:
            self.events.append("candidate")
        return list(self.candidates)


class StubPredictor:
    def __init__(
        self,
        predictions: dict[str, PredictionResult] | None = None,
        events: list[str] | None = None,
    ):
        self.predictions = predictions or {}
        self.events = events
        self.calls: list[str] = []

    def predict(
        self,
        context: DecisionContext,
        candidate: CandidateAction,
    ) -> PredictionResult:
        self.calls.append(candidate.id)
        if self.events is not None:
            self.events.append(f"prediction:{candidate.id}")
        return self.predictions.get(candidate.id, _prediction(candidate))


class StubScorer:
    def __init__(
        self,
        scores: dict[str, DecisionScore] | None = None,
        events: list[str] | None = None,
    ):
        self.scores = scores or {}
        self.events = events
        self.calls: list[str] = []
        self.predictions: list[PredictionResult] = []

    def score(
        self,
        candidate: CandidateAction,
        prediction: PredictionResult,
    ) -> DecisionScore:
        self.calls.append(candidate.id)
        self.predictions.append(prediction)
        if self.events is not None:
            self.events.append(f"scoring:{candidate.id}")
        return self.scores.get(
            candidate.id,
            _score(candidate, utility_score=prediction.confidence),
        )


class StubRanker:
    def __init__(
        self,
        ordered_ids: list[str] | None = None,
        events: list[str] | None = None,
    ):
        self.ordered_ids = ordered_ids
        self.events = events
        self.candidates_seen: list[CandidateAction] = []
        self.scores_seen: list[DecisionScore] = []

    def rank(
        self,
        candidates: list[CandidateAction],
        scores: list[DecisionScore],
    ) -> list[RankedCandidate]:
        if self.events is not None:
            self.events.append("ranking")
        self.candidates_seen = list(candidates)
        self.scores_seen = list(scores)
        candidate_by_id = {item.id: item for item in candidates}
        score_by_id = {item.candidate_id: item for item in scores}
        ordered_ids = self.ordered_ids or [item.id for item in candidates]
        return [
            RankedCandidate(
                rank=index,
                candidate=candidate_by_id[candidate_id],
                score=score_by_id[candidate_id],
            )
            for index, candidate_id in enumerate(ordered_ids, start=1)
        ]


class StubConfidenceEngine:
    def __init__(
        self,
        results: dict[str, DecisionConfidenceResult] | None = None,
        events: list[str] | None = None,
    ):
        self.results = results or {}
        self.events = events
        self.calls: list[str] = []

    def evaluate(
        self,
        context: DecisionContext,
        prediction: PredictionResult,
    ) -> DecisionConfidenceResult:
        self.calls.append(prediction.candidate_id)
        if self.events is not None:
            self.events.append("confidence")
        return self.results.get(
            prediction.candidate_id,
            _confidence(
                prediction.candidate_id,
                prediction_reliability=prediction.confidence,
            ),
        )


def _policy_evaluator(
    allowed_ids: set[str],
    events: list[str] | None = None,
):
    def evaluate(
        policy: DecisionPolicy,
        candidate: CandidateAction,
        context: DecisionContext,
    ) -> PolicyResult:
        if events is not None:
            events.append(f"policy:{candidate.id}")
        if candidate.id in allowed_ids:
            return PolicyResult(allowed=True, violations=[])
        return PolicyResult(
            allowed=False,
            violations=["unsupported_cognitive_basis"],
        )

    return evaluate


def _engine(
    candidates: list[CandidateAction],
    *,
    allowed_ids: set[str] | None = None,
    predictor: StubPredictor | None = None,
    scorer: StubScorer | None = None,
    ranker: StubRanker | None = None,
    confidence_engine: StubConfidenceEngine | None = None,
    events: list[str] | None = None,
) -> DecisionEngine:
    allowed = {candidate.id for candidate in candidates} if allowed_ids is None else allowed_ids
    return DecisionEngine(
        candidate_generator=StubGenerator(candidates, events),
        policy=_policy(),
        predictor=predictor or StubPredictor(events=events),
        scorer=scorer or StubScorer(events=events),
        ranker=ranker or StubRanker(events=events),
        confidence_engine=confidence_engine or StubConfidenceEngine(events=events),
        policy_evaluator=_policy_evaluator(allowed, events),
    )


def test_engine_constructs_with_existing_phase_4_to_9_collaborators():
    predictor: OutcomePredictor = StubPredictor()
    engine = DecisionEngine(
        candidate_generator=CandidateGenerator(),
        policy=_policy(),
        predictor=predictor,
        scorer=DecisionScorer(),
        ranker=DecisionRanker(),
        confidence_engine=DecisionConfidenceEngine(),
    )

    assert isinstance(engine, DecisionEngine)


def test_empty_safe_context_selects_no_action_deterministically():
    result = DecisionEngine(
        candidate_generator=CandidateGenerator(),
        policy=_policy(),
        predictor=StubPredictor(),
        scorer=DecisionScorer(),
        ranker=DecisionRanker(),
        confidence_engine=DecisionConfidenceEngine(),
    ).evaluate(_context())

    assert result.selected_action is not None
    assert result.selected_action.action_type is ActionType.NO_ACTION
    assert result.state == DecisionState.APPROVED.value


def test_pipeline_order_is_candidate_policy_prediction_scoring_ranking_confidence():
    events: list[str] = []
    candidate = _candidate("candidate-a", ActionType.NO_ACTION)
    result = _engine([candidate], events=events).evaluate(_context())

    assert result.selected_action == candidate
    assert events == [
        "candidate",
        "policy:candidate-a",
        "prediction:candidate-a",
        "scoring:candidate-a",
        "ranking",
        "confidence",
    ]


def test_policy_rejected_candidate_is_not_predicted_scored_or_ranked():
    allowed = _candidate("allowed", ActionType.NO_ACTION)
    rejected = _candidate("rejected", ActionType.EVALUATE_NETWORK)
    predictor = StubPredictor()
    scorer = StubScorer()
    ranker = StubRanker()

    result = _engine(
        [allowed, rejected],
        allowed_ids={"allowed"},
        predictor=predictor,
        scorer=scorer,
        ranker=ranker,
    ).evaluate(_context())

    assert predictor.calls == ["allowed"]
    assert scorer.calls == ["allowed"]
    assert [item.id for item in ranker.candidates_seen] == ["allowed"]
    assert result.rejected_alternatives == [rejected]


def test_policy_approved_candidate_proceeds_to_predictor():
    candidate = _candidate("allowed", ActionType.NO_ACTION)
    predictor = StubPredictor()

    _engine([candidate], predictor=predictor).evaluate(_context())

    assert predictor.calls == ["allowed"]


def test_prediction_result_is_passed_to_scorer_unchanged():
    candidate = _candidate("allowed", ActionType.NO_ACTION)
    prediction = _prediction(candidate, confidence=0.61)
    predictor = StubPredictor({"allowed": prediction})
    scorer = StubScorer()

    _engine([candidate], predictor=predictor, scorer=scorer).evaluate(_context())

    assert scorer.predictions == [prediction]


def test_decision_score_is_passed_to_ranker_unchanged():
    candidate = _candidate("allowed", ActionType.NO_ACTION)
    score = _score(candidate, utility_score=0.731)
    scorer = StubScorer({"allowed": score})
    ranker = StubRanker()

    _engine([candidate], scorer=scorer, ranker=ranker).evaluate(_context())

    assert ranker.scores_seen == [score]
    assert ranker.scores_seen[0].utility_score == 0.731


def test_highest_ranked_candidate_becomes_selected_action():
    first = _candidate("first", ActionType.NO_ACTION)
    second = _candidate("second", ActionType.EVALUATE_NETWORK)
    ranker = StubRanker(["second", "first"])

    result = _engine([first, second], ranker=ranker).evaluate(_context())

    assert result.selected_action == second


def test_remaining_ranked_candidates_become_alternatives_in_ranker_order():
    first = _candidate("first", ActionType.NO_ACTION)
    second = _candidate("second", ActionType.EVALUATE_NETWORK)
    third = _candidate("third", ActionType.EVALUATE_EFFICIENCY)
    ranker = StubRanker(["third", "first", "second"])

    result = _engine([first, second, third], ranker=ranker).evaluate(_context())

    assert result.selected_action == third
    assert result.alternatives == [first, second]


def test_rejected_candidates_are_not_mixed_into_eligible_alternatives():
    selected = _candidate("selected", ActionType.NO_ACTION)
    alternative = _candidate("alternative", ActionType.EVALUATE_NETWORK)
    rejected = _candidate("rejected", ActionType.EVALUATE_EFFICIENCY)
    ranker = StubRanker(["selected", "alternative"])

    result = _engine(
        [selected, alternative, rejected],
        allowed_ids={"selected", "alternative"},
        ranker=ranker,
    ).evaluate(_context())

    assert result.alternatives == [alternative]
    assert result.rejected_alternatives == [rejected]


def test_candidate_identity_is_preserved_across_pipeline():
    candidate = _candidate("identity", ActionType.NO_ACTION)
    prediction = _prediction(candidate)
    score = _score(candidate, utility_score=0.4)
    predictor = StubPredictor({candidate.id: prediction})
    scorer = StubScorer({candidate.id: score})
    ranker = StubRanker([candidate.id])

    result = _engine(
        [candidate],
        predictor=predictor,
        scorer=scorer,
        ranker=ranker,
    ).evaluate(_context())

    assert predictor.calls == ["identity"]
    assert scorer.calls == ["identity"]
    assert ranker.scores_seen[0].candidate_id == "identity"
    assert result.selected_action is candidate


def test_no_action_can_be_selected_naturally_from_ranker_output():
    hold = _candidate("hold", ActionType.NO_ACTION)
    evaluate = _candidate("evaluate", ActionType.EVALUATE_NETWORK)

    result = _engine(
        [hold, evaluate],
        ranker=StubRanker(["hold", "evaluate"]),
    ).evaluate(_context())

    assert result.selected_action == hold


def test_no_action_receives_no_orchestration_bonus():
    hold = _candidate("hold", ActionType.NO_ACTION)
    evaluate = _candidate("evaluate", ActionType.EVALUATE_NETWORK)

    result = _engine(
        [hold, evaluate],
        ranker=StubRanker(["evaluate", "hold"]),
    ).evaluate(_context())

    assert result.selected_action == evaluate


def test_no_action_receives_no_orchestration_penalty():
    hold = _candidate("hold", ActionType.NO_ACTION)
    evaluate = _candidate("evaluate", ActionType.EVALUATE_NETWORK)

    result = _engine(
        [hold, evaluate],
        ranker=StubRanker(["hold", "evaluate"]),
    ).evaluate(_context())

    assert result.selected_action == hold


def test_engine_does_not_fabricate_no_action_when_generator_does_not_return_it():
    candidate = _candidate("network", ActionType.EVALUATE_NETWORK)

    result = _engine([candidate]).evaluate(_context())

    all_ids = [
        result.selected_action.id if result.selected_action else "",
        *[item.id for item in result.alternatives],
        *[item.id for item in result.rejected_alternatives],
    ]
    assert "candidate-no_action" not in all_ids


def test_all_policy_rejected_raises_explicit_safe_error():
    candidate = _candidate("rejected", ActionType.EVALUATE_NETWORK)
    predictor = StubPredictor()
    scorer = StubScorer()
    ranker = StubRanker()

    with pytest.raises(NoAdmissibleCandidateError):
        _engine(
            [candidate],
            allowed_ids=set(),
            predictor=predictor,
            scorer=scorer,
            ranker=ranker,
        ).evaluate(_context())

    assert predictor.calls == []
    assert scorer.calls == []
    assert ranker.candidates_seen == []


def test_phase_9_confidence_component_is_used_without_new_formula():
    candidate = _candidate("candidate", ActionType.NO_ACTION)
    confidence_engine = StubConfidenceEngine(
        {"candidate": _confidence("candidate", prediction_reliability=0.67)}
    )

    result = _engine(
        [candidate],
        confidence_engine=confidence_engine,
    ).evaluate(_context())

    assert result.confidence == 0.67
    assert "confidence_source=prediction_reliability" in result.explanation
    assert "numeric_evidence_quality_unavailable" in result.explanation


def test_available_phase_9_overall_confidence_is_used_directly():
    candidate = _candidate("candidate", ActionType.NO_ACTION)
    confidence_engine = StubConfidenceEngine(
        {
            "candidate": _confidence(
                "candidate",
                prediction_reliability=0.67,
                overall_confidence=0.42,
            )
        }
    )

    result = _engine(
        [candidate],
        confidence_engine=confidence_engine,
    ).evaluate(_context())

    assert result.confidence == 0.42
    assert "confidence_source=overall_confidence" in result.explanation


def test_confidence_does_not_modify_decision_utility_score():
    candidate = _candidate("candidate", ActionType.NO_ACTION)
    score = _score(candidate, utility_score=0.123456)
    scorer = StubScorer({"candidate": score})
    ranker = StubRanker()

    _engine(
        [candidate],
        scorer=scorer,
        ranker=ranker,
    ).evaluate(_context())

    assert score.utility_score == 0.123456
    assert ranker.scores_seen[0].utility_score == 0.123456


def test_confidence_does_not_modify_ranker_order():
    first = _candidate("first", ActionType.NO_ACTION)
    second = _candidate("second", ActionType.EVALUATE_NETWORK)
    ranker = StubRanker(["second", "first"])
    confidence_engine = StubConfidenceEngine(
        {
            "second": _confidence("second", prediction_reliability=0.01),
            "first": _confidence("first", prediction_reliability=1.0),
        }
    )

    result = _engine(
        [first, second],
        ranker=ranker,
        confidence_engine=confidence_engine,
    ).evaluate(_context())

    assert result.selected_action == second
    assert result.alternatives == [first]


def test_explanation_is_deterministic_and_structured():
    allowed = _candidate("allowed", ActionType.NO_ACTION)
    rejected = _candidate("rejected", ActionType.EVALUATE_NETWORK)
    engine = _engine(
        [allowed, rejected],
        allowed_ids={"allowed"},
    )

    first = engine.evaluate(_context())
    second = engine.evaluate(_context())

    assert first.explanation == second.explanation
    assert "selected=allowed" in first.explanation
    assert "rejected_alternatives=1" in first.explanation
    assert "unsupported_cognitive_basis" in first.explanation


def test_same_inputs_and_collaborators_produce_identical_result():
    candidate = _candidate("candidate", ActionType.NO_ACTION)
    engine = _engine([candidate])
    context = _context()

    assert engine.evaluate(context) == engine.evaluate(context)


def test_engine_does_not_mutate_decision_context_or_cognitive_objects():
    context = _cognitive_context()
    before = context.model_dump(mode="json")
    evidence_before = deepcopy(context.evidence[0])
    claim_before = deepcopy(context.claims[0])
    hypothesis_before = deepcopy(context.hypotheses[0])
    candidate = _candidate("candidate", ActionType.NO_ACTION)

    _engine([candidate]).evaluate(context)

    assert context.model_dump(mode="json") == before
    assert context.evidence[0] == evidence_before
    assert context.claims[0] == claim_before
    assert context.hypotheses[0] == hypothesis_before


def test_engine_does_not_mutate_candidate_prediction_or_score():
    candidate = _candidate("candidate", ActionType.NO_ACTION)
    prediction = _prediction(candidate)
    score = _score(candidate, utility_score=0.33)
    candidate_before = deepcopy(candidate)
    prediction_before = deepcopy(prediction)
    score_before = deepcopy(score)

    _engine(
        [candidate],
        predictor=StubPredictor({"candidate": prediction}),
        scorer=StubScorer({"candidate": score}),
    ).evaluate(_context())

    assert candidate == candidate_before
    assert prediction == prediction_before
    assert score == score_before


def test_prediction_identity_mismatch_fails_safely():
    candidate = _candidate("candidate", ActionType.NO_ACTION)
    wrong = PredictionResult(
        candidate_id="other",
        expected_reward_change=None,
        expected_hashrate_change=None,
        expected_power_change=None,
        confidence=0.8,
        uncertainty=0.1,
        horizon=PredictionHorizon.SHORT_TERM,
    )

    with pytest.raises(ValueError, match="prediction candidate_id"):
        _engine(
            [candidate],
            predictor=StubPredictor({"candidate": wrong}),
        ).evaluate(_context())


def test_score_identity_mismatch_fails_safely():
    candidate = _candidate("candidate", ActionType.NO_ACTION)
    wrong_score = DecisionScore(
        candidate_id="other",
        benefit=0.0,
        confidence=0.8,
        risk=0.0,
        action_cost=0.0,
        uncertainty=0.1,
        utility_score=-0.1,
    )

    with pytest.raises(ValueError, match="DecisionScore candidate_id"):
        _engine(
            [candidate],
            scorer=StubScorer({"candidate": wrong_score}),
        ).evaluate(_context())


class UnknownCandidateRanker:
    def rank(
        self,
        candidates: list[CandidateAction],
        scores: list[DecisionScore],
    ) -> list[RankedCandidate]:
        unknown = _candidate("unknown", ActionType.EVALUATE_NETWORK)
        return [
            RankedCandidate(
                rank=1,
                candidate=unknown,
                score=DecisionScore(
                    candidate_id="unknown",
                    benefit=0.0,
                    confidence=0.8,
                    risk=0.0,
                    action_cost=0.0,
                    uncertainty=0.1,
                    utility_score=-0.1,
                ),
            )
        ]


def test_ranking_unknown_candidate_mismatch_fails_safely():
    candidate = _candidate("candidate", ActionType.NO_ACTION)

    with pytest.raises(ValueError, match="ranking references unknown candidate"):
        DecisionEngine(
            candidate_generator=StubGenerator([candidate]),
            policy=_policy(),
            predictor=StubPredictor(),
            scorer=StubScorer(),
            ranker=UnknownCandidateRanker(),
            confidence_engine=StubConfidenceEngine(),
            policy_evaluator=_policy_evaluator({"candidate"}),
        ).evaluate(_context())


def test_duplicate_generated_candidate_ids_fail_safely():
    first = _candidate("duplicate", ActionType.NO_ACTION)
    second = _candidate("duplicate", ActionType.EVALUATE_NETWORK)

    with pytest.raises(ValueError, match="duplicate candidate id"):
        _engine([first, second]).evaluate(_context())


def test_incompatible_policy_result_fails_safely():
    candidate = _candidate("candidate", ActionType.NO_ACTION)

    def invalid_policy(*args):
        return True

    engine = DecisionEngine(
        candidate_generator=StubGenerator([candidate]),
        policy=_policy(),
        predictor=StubPredictor(),
        scorer=StubScorer(),
        ranker=StubRanker(),
        confidence_engine=StubConfidenceEngine(),
        policy_evaluator=invalid_policy,
    )

    with pytest.raises(TypeError, match="PolicyResult"):
        engine.evaluate(_context())


def test_confidence_identity_mismatch_fails_safely():
    candidate = _candidate("candidate", ActionType.NO_ACTION)
    confidence_engine = StubConfidenceEngine(
        {"candidate": _confidence("other")}
    )

    with pytest.raises(ValueError, match="confidence result candidate_id"):
        _engine(
            [candidate],
            confidence_engine=confidence_engine,
        ).evaluate(_context())


def test_ranking_output_score_must_be_exact_scorer_output():
    candidate = _candidate("candidate", ActionType.NO_ACTION)
    source_score = _score(candidate, utility_score=0.2)

    class AlteringRanker:
        def rank(self, candidates, scores):
            altered = scores[0].model_copy(update={"utility_score": 9.0})
            return [
                RankedCandidate(
                    rank=1,
                    candidate=candidates[0],
                    score=altered,
                )
            ]

    with pytest.raises(ValueError, match="ranking altered DecisionScore"):
        DecisionEngine(
            candidate_generator=StubGenerator([candidate]),
            policy=_policy(),
            predictor=StubPredictor(),
            scorer=StubScorer({"candidate": source_score}),
            ranker=AlteringRanker(),
            confidence_engine=StubConfidenceEngine(),
            policy_evaluator=_policy_evaluator({"candidate"}),
        ).evaluate(_context())

    assert source_score.utility_score == 0.2


def test_ranker_output_is_used_exactly_without_engine_resorting():
    low = _candidate("low", ActionType.NO_ACTION)
    high = _candidate("high", ActionType.EVALUATE_NETWORK)
    scorer = StubScorer(
        {
            "low": _score(low, utility_score=-5.0),
            "high": _score(high, utility_score=100.0),
        }
    )
    ranker = StubRanker(["low", "high"])

    result = _engine(
        [low, high],
        scorer=scorer,
        ranker=ranker,
    ).evaluate(_context())

    assert result.selected_action == low
    assert result.alternatives == [high]


def test_policy_gate_regression_allowed_flows_rejected_stops():
    allowed = _candidate("allowed", ActionType.NO_ACTION)
    rejected = _candidate("rejected", ActionType.EVALUATE_NETWORK)
    predictor = StubPredictor()
    scorer = StubScorer()
    ranker = StubRanker(["allowed"])

    result = _engine(
        [allowed, rejected],
        allowed_ids={"allowed"},
        predictor=predictor,
        scorer=scorer,
        ranker=ranker,
    ).evaluate(_context())

    assert predictor.calls == ["allowed"]
    assert scorer.calls == ["allowed"]
    assert [item.id for item in ranker.candidates_seen] == ["allowed"]
    assert result.rejected_alternatives == [rejected]


def test_phase_1_through_9_contracts_remain_importable_and_compatible():
    assert ActionType.NO_ACTION.value == "no_action"
    assert ExecutionCategory.OBSERVATION_ONLY.value == "observation_only"
    assert DecisionResult.model_fields["selected_action"].annotation is not None
    assert can_transition(DecisionState.DETECTED, DecisionState.ANALYZING)
    assert isinstance(DecisionContext(), DecisionContext)
    assert isinstance(CandidateGenerator(), CandidateGenerator)
    assert isinstance(_policy(), DecisionPolicy)
    assert OutcomePredictor is not None
    assert isinstance(DecisionScorer(), DecisionScorer)
    assert isinstance(DecisionRanker(), DecisionRanker)
    assert isinstance(DecisionConfidenceEngine(), DecisionConfidenceEngine)


def test_result_uses_phase_2_lifecycle_state_not_free_form_new_state():
    candidate = _candidate("candidate", ActionType.NO_ACTION)

    result = _engine([candidate]).evaluate(_context())

    assert result.state == DecisionState.APPROVED.value
    assert result.state in {state.value for state in DecisionState}


def test_rejection_reasons_are_preserved_in_explanation_without_new_model():
    allowed = _candidate("allowed", ActionType.NO_ACTION)
    rejected = _candidate("rejected", ActionType.EVALUATE_NETWORK)

    result = _engine(
        [allowed, rejected],
        allowed_ids={"allowed"},
    ).evaluate(_context())

    assert "rejected:unsupported_cognitive_basis" in result.explanation


def test_decision_id_is_deterministic_and_contains_selected_identity():
    candidate = _candidate("candidate", ActionType.NO_ACTION)
    engine = _engine([candidate])

    first = engine.evaluate(_context())
    second = engine.evaluate(_context())

    assert first.decision_id == "decision-candidate"
    assert second.decision_id == first.decision_id


def test_engine_has_no_agent_working_memory_dependency():
    from mining_guardian.agent.decision.engine import DecisionEngine as Engine

    assert "AgentWorkingMemory" not in Engine.evaluate.__annotations__.values()


def test_engine_source_contains_no_execution_or_external_io_capability():
    import inspect

    import mining_guardian.agent.decision.engine as engine_module

    source = inspect.getsource(engine_module).lower()
    forbidden = (
        "subprocess",
        "os.system",
        "shell=true",
        "requests.",
        "httpx.",
        "srbminer",
        "nvml",
        "restart_miner",
        "switch_pool",
        "switch_endpoint",
        "switch_algorithm",
        "wallet",
        ".execute(",
        ".apply(",
        "openai",
        "anthropic",
    )

    assert all(token not in source for token in forbidden)


def test_engine_does_not_import_persistence_or_cli_layers():
    import inspect

    import mining_guardian.agent.decision.engine as engine_module

    source = inspect.getsource(engine_module)

    assert "storage" not in source
    assert "cli" not in source
