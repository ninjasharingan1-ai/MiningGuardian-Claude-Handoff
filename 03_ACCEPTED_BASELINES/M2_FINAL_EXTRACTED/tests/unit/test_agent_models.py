from datetime import datetime

import pytest
from pydantic import ValidationError

from mining_guardian.agent.models import (
    AgentHypothesis,
    AgentLesson,
    AgentOutcome,
    AgentProposal,
    HypothesisStatus,
    LessonScope,
    ProposalType,
    TelemetryWindowSummary,
)


def test_hypothesis_confidence_is_bounded():
    hypothesis = AgentHypothesis(
        statement="Hashrate is stable within the observed window.",
        confidence=0.7,
        status=HypothesisStatus.ACTIVE,
    )
    assert hypothesis.confidence == 0.7
    with pytest.raises(ValidationError):
        AgentHypothesis(statement="invalid", confidence=1.1)


def test_proposal_supports_only_shadow_safe_types():
    proposal = AgentProposal(
        proposal_type=ProposalType.OBSERVE_LONGER,
        rationale="More evidence is needed.",
        desired_evidence=["30m hashrate window"],
        confidence=0.6,
        evaluation_horizon_seconds=1800,
    )
    assert proposal.proposal_type is ProposalType.OBSERVE_LONGER
    with pytest.raises(ValidationError):
        AgentProposal(
            proposal_type="set_gpu_clock",
            rationale="forbidden",
            confidence=1.0,
        )


def test_outcome_and_lesson_models_preserve_scope_without_claiming_causality():
    outcome = AgentOutcome(
        decision_id="decision_1",
        timestamp=datetime(2026, 9, 16, 0, 0, 0),
        observations=["Hashrate remained within the previous range."],
        supports_proposal=None,
    )
    lesson = AgentLesson(
        timestamp=datetime(2026, 9, 16, 0, 5, 0),
        claim="Observed stability applied to this session and algorithm only.",
        supporting_observations=["window_5m"],
        confidence=0.5,
        scope=LessonScope(
            session_id="session_1",
            algorithm_id="pearlpow",
            miner="srbminer",
            gpu_ids=[0],
        ),
        algorithm_id="pearlpow",
        hardware_identity={"nvml_gpu_index": 0},
    )
    assert outcome.supports_proposal is None
    assert lesson.scope.algorithm_id == "pearlpow"
    assert lesson.hardware_identity["nvml_gpu_index"] == 0


def test_lesson_confidence_is_bounded():
    with pytest.raises(ValidationError):
        AgentLesson(
            timestamp=datetime.now(),
            claim="invalid",
            confidence=-0.1,
        )


def test_legacy_context_window_without_temporal_metadata_remains_readable():
    window = TelemetryWindowSummary.model_validate(
        {
            "label": "5m",
            "start_time": "2026-09-16T03:17:45",
            "end_time": "2026-09-16T03:18:46",
            "duration_seconds": 61.0,
            "miner_sample_count": 6,
            "hardware_sample_count": 6,
            "workloads": [],
            "gpus": [],
        }
    )
    assert window.latest_sample_at is None
    assert window.freshness.value == "unknown"
    assert window.session_status.value == "unknown"
