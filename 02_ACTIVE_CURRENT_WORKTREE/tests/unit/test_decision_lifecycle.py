import json

import pytest

from mining_guardian.agent.decision import (
    ActionType,
    CandidateAction,
    DecisionResult,
    ExecutionCategory,
)
from mining_guardian.agent.decision.lifecycle import DecisionState, can_transition


def test_decision_state_serialization_and_values_are_stable():
    expected_values = {
        DecisionState.DETECTED: "detected",
        DecisionState.ANALYZING: "analyzing",
        DecisionState.PROPOSED: "proposed",
        DecisionState.VALIDATING: "validating",
        DecisionState.APPROVED: "approved",
        DecisionState.REJECTED: "rejected",
        DecisionState.OBSERVED: "observed",
        DecisionState.LEARNED: "learned",
    }

    assert {state: state.value for state in DecisionState} == expected_values
    assert json.loads(json.dumps(list(DecisionState))) == list(expected_values.values())


@pytest.mark.parametrize(
    ("current_state", "next_state"),
    [
        (DecisionState.DETECTED, DecisionState.ANALYZING),
        (DecisionState.ANALYZING, DecisionState.PROPOSED),
        (DecisionState.PROPOSED, DecisionState.VALIDATING),
        (DecisionState.VALIDATING, DecisionState.APPROVED),
        (DecisionState.VALIDATING, DecisionState.REJECTED),
        (DecisionState.APPROVED, DecisionState.OBSERVED),
        (DecisionState.OBSERVED, DecisionState.LEARNED),
        (DecisionState.REJECTED, DecisionState.LEARNED),
    ],
)
def test_valid_transitions_are_accepted(
    current_state: DecisionState,
    next_state: DecisionState,
):
    assert can_transition(current_state, next_state)


@pytest.mark.parametrize(
    ("current_state", "next_state"),
    [
        (DecisionState.DETECTED, DecisionState.LEARNED),
        (DecisionState.PROPOSED, DecisionState.APPROVED),
        (DecisionState.APPROVED, DecisionState.ANALYZING),
        (DecisionState.OBSERVED, DecisionState.DETECTED),
    ],
)
def test_invalid_transitions_are_rejected(
    current_state: DecisionState,
    next_state: DecisionState,
):
    assert not can_transition(current_state, next_state)


def test_phase_one_contracts_remain_compatible():
    action = CandidateAction(
        id="phase-1-action",
        action_type=ActionType.NO_ACTION,
        description="Preserve current state",
        execution_category=ExecutionCategory.OBSERVATION_ONLY,
    )
    result = DecisionResult(
        decision_id="phase-1-result",
        state=DecisionState.PROPOSED.value,
        selected_action=action,
        explanation="Phase 1 contracts remain importable and usable.",
    )

    assert result.selected_action == action
    assert result.state == "proposed"
