from enum import StrEnum


class DecisionState(StrEnum):
    """Reasoning-stage state for a decision proposal."""

    DETECTED = "detected"
    ANALYZING = "analyzing"
    PROPOSED = "proposed"
    VALIDATING = "validating"
    APPROVED = "approved"
    REJECTED = "rejected"
    OBSERVED = "observed"
    LEARNED = "learned"


_ALLOWED_TRANSITIONS: dict[DecisionState, frozenset[DecisionState]] = {
    DecisionState.DETECTED: frozenset({DecisionState.ANALYZING}),
    DecisionState.ANALYZING: frozenset({DecisionState.PROPOSED}),
    DecisionState.PROPOSED: frozenset({DecisionState.VALIDATING}),
    DecisionState.VALIDATING: frozenset(
        {
            DecisionState.APPROVED,
            DecisionState.REJECTED,
        }
    ),
    DecisionState.APPROVED: frozenset({DecisionState.OBSERVED}),
    DecisionState.REJECTED: frozenset({DecisionState.LEARNED}),
    DecisionState.OBSERVED: frozenset({DecisionState.LEARNED}),
    DecisionState.LEARNED: frozenset(),
}


def can_transition(
    current_state: DecisionState,
    next_state: DecisionState,
) -> bool:
    """Return whether the decision reasoning lifecycle permits the transition."""
    return next_state in _ALLOWED_TRANSITIONS[current_state]
