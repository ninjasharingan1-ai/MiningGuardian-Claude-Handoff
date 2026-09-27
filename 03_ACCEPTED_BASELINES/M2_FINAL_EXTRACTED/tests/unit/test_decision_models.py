from mining_guardian.agent.decision import (
    ActionType,
    CandidateAction,
    DecisionResult,
    ExecutionCategory,
)


def test_candidate_action_round_trip():
    action = CandidateAction(
        id="decision-1",
        action_type=ActionType.EVALUATE_EFFICIENCY,
        description="Evaluate efficiency profile",
        execution_category=ExecutionCategory.RECOMMENDATION_ONLY,
        expected_gain=0.5,
        confidence=0.8,
        risk_score=0.2,
        transition_cost=0.1,
    )

    restored = CandidateAction.model_validate_json(action.model_dump_json())

    assert restored == action


def test_candidate_action_rejects_invalid_values():
    try:
        CandidateAction(
            id="decision-1",
            action_type=ActionType.NO_ACTION,
            description="No action",
            execution_category=ExecutionCategory.OBSERVATION_ONLY,
            confidence=2.0,
        )
    except ValueError:
        return

    raise AssertionError("invalid confidence should fail")


def test_decision_result_preserves_rejected_alternatives():
    rejected = CandidateAction(
        id="decision-2",
        action_type=ActionType.EVALUATE_NETWORK,
        description="Evaluate network",
        execution_category=ExecutionCategory.SIMULATION_ONLY,
    )
    result = DecisionResult(
        decision_id="result-1",
        state="proposed",
        rejected_alternatives=[rejected],
        explanation="Alternative rejected due to uncertainty.",
    )

    restored = DecisionResult.model_validate_json(result.model_dump_json())

    assert restored.rejected_alternatives == [rejected]
