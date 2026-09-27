"""Provider-neutral reasoning gateway for M2.1."""

from typing import Protocol

from .models import (
    AgentProposal,
    AgentReasoningResult,
    AgentWorkingMemory,
    ProposalType,
)


class ModelGateway(Protocol):
    """The only interface the Shadow Agent uses for model reasoning."""

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def reason(self, context: AgentWorkingMemory) -> AgentReasoningResult: ...


class FakeModelGateway:
    """Deterministic, network-free gateway used by tests and M2.1 shadow CLI."""

    provider_name = "fake"
    model_name = "deterministic-m2.1"

    def reason(self, context: AgentWorkingMemory) -> AgentReasoningResult:
        missing = list(context.world_state.missing_signals)
        desired_evidence = missing[:5]
        return AgentReasoningResult(
            hypotheses=[],
            evidence=[
                "M2.1 deterministic fake gateway does not infer or execute control actions."
            ],
            missing_evidence=missing,
            proposal=AgentProposal(
                proposal_type=ProposalType.NO_ACTION,
                rationale="Shadow-mode fake gateway always proposes NO_ACTION.",
                expected_observation=None,
                desired_evidence=desired_evidence,
                confidence=1.0,
                evaluation_horizon_seconds=None,
            ),
            confidence=1.0,
        )
