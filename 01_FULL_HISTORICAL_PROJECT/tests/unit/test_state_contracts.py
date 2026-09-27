"""M3.2-S1 contract tests; no estimation, persistence or live sources."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from mining_guardian.observability.models import Freshness, Quality, RuntimeObservation, Source
from mining_guardian.state.contracts import (
    CheckResult,
    ConflictKind,
    ConflictResolutionStatus,
    EstimatedState,
    EstimatedStateField,
    EvidenceCompleteness,
    EvidenceDisposition,
    FieldEvidenceContract,
    FieldRequest,
    LastKnownContext,
    ProductionMetadata,
    SignalRequirement,
    SnapshotCompleteness,
    StateConfidence,
    StateConflict,
    StateEvidenceReference,
    StateSnapshot,
    StateUncertainty,
    StateValidity,
    SupportCheck,
    SupportCheckKind,
    SupportStatus,
    TimeBasis,
    UncertaintyAssessment,
    UncertaintyDimension,
    UncertaintyStatus,
)

T = datetime(2026, 1, 1, tzinfo=UTC)
DIGEST = "a" * 64


def evidence(*, disposition: EvidenceDisposition = EvidenceDisposition.SUPPORTING) -> StateEvidenceReference:
    raw = RuntimeObservation(
        source=Source.NVML, source_instance="uuid:GPU-1", signal="temperature_c",
        value=0, unit="degC", observation_time=T, ingestion_time=T,
        correlation_id=uuid4(), quality=Quality.VALID,
    )
    return StateEvidenceReference(
        observation_id=raw.observation_id, observation_schema_version=raw.schema_version,
        payload_sha256=DIGEST, source=raw.source.value, source_instance=raw.source_instance,
        signal=raw.signal, unit=raw.unit, event_time=raw.event_time,
        observation_time=raw.observation_time, ingestion_time=raw.ingestion_time,
        processing_time=raw.processing_time, guardian_session_id=raw.guardian_session_id,
        correlation_id=raw.correlation_id, input_quality=raw.quality,
        input_quality_conditions=raw.quality_conditions, recorded_freshness=raw.freshness,
        temporal_assessment="eligible_under_field_contract", disposition=disposition,
        reason="declared_test_evidence",
    )


def confidence(status: SupportStatus = SupportStatus.SUPPORTED) -> StateConfidence:
    checks = (
        SupportCheck(check_id="minimum", kind=SupportCheckKind.MINIMUM, result=CheckResult.PASS),
        SupportCheck(check_id="corroboration", kind=SupportCheckKind.STRENGTHENING,
                     result=CheckResult.UNKNOWN if status == SupportStatus.LIMITED else CheckResult.PASS),
    ) if status != SupportStatus.UNASSESSED else ()
    return StateConfidence(
        interpretation="CURRENT_ESTIMATE_SUPPORT", rubric_id="test-rubric",
        rubric_version="v1", support_status=status, support_checks=checks,
    )


def uncertainty() -> StateUncertainty:
    return StateUncertainty(dimensions={
        dimension: UncertaintyAssessment(status=UncertaintyStatus.UNKNOWN, reason="not_characterized")
        for dimension in UncertaintyDimension
    })


def completeness() -> EvidenceCompleteness:
    return EvidenceCompleteness(required=("temperature",), satisfied=("temperature",),
                                unavailable=(), conflicting=(), optional_support=())


def field(*, validity: StateValidity = StateValidity.VALID, value=0,
          ref: StateEvidenceReference | None = None, **changes) -> EstimatedStateField:
    if ref is None:
        ref = evidence()
    data = {
        "field_key": "temperature_c", "subject_scope": "uuid:GPU-1", "definition_version": "v1",
        "value": value, "unit": "degC", "state_reference_time": T, "validity": validity,
        "confidence": confidence(SupportStatus.UNASSESSED if value is None else SupportStatus.SUPPORTED),
        "uncertainty": uncertainty(), "evidence_completeness": completeness(),
        "freshness_assessment": "source_time_current_under_explicit_contract",
        "method_name": "latest_eligible_observed_value", "method_version": "v1",
        "field_contract_id": "gpu-temperature", "field_contract_version": "v1",
        "configuration": {"window_seconds": 30}, "configuration_sha256": DIGEST,
        "evidence_refs": (ref,),
    }
    data.update(changes)
    return EstimatedStateField(**data)


def snapshot(*fields: EstimatedStateField,
             completeness_status: SnapshotCompleteness) -> StateSnapshot:
    requested = tuple(FieldRequest(field_key=f.field_key, subject_scope=f.subject_scope) for f in fields)
    usable = tuple(r for r, f in zip(requested, fields, strict=True)
                   if f.validity in (StateValidity.VALID, StateValidity.DEGRADED))
    unavailable = tuple(r for r, f in zip(requested, fields, strict=True)
                        if f.validity == StateValidity.UNKNOWN)
    invalid = tuple(r for r, f in zip(requested, fields, strict=True)
                    if f.validity == StateValidity.INVALID)
    return StateSnapshot(state_reference_time=T, requested_fields=requested, fields=fields,
                         completeness=completeness_status, usable_fields=usable,
                         unavailable_fields=unavailable, invalid_fields=invalid,
                         input_manifest_id=DIGEST)


def test_zero_is_valid_and_full_artifact_round_trips_without_identity_collapse():
    first = field()
    semantic = snapshot(first, completeness_status=SnapshotCompleteness.COMPLETE)
    state = EstimatedState(state_type="gpu_current", snapshot=semantic,
                           semantic_content_id=DIGEST,
                           production=ProductionMetadata(artifact_id=uuid4(), estimated_at=T + timedelta(days=1)))
    restored = EstimatedState.model_validate_json(state.model_dump_json())
    assert restored == state
    assert restored.snapshot.fields[0].value == 0
    assert restored.state_id == state.production.artifact_id
    assert restored.effective_time == T
    assert restored.production.estimated_at != restored.effective_time
    later = state.model_copy(update={"production": ProductionMetadata(
        artifact_id=uuid4(), estimated_at=T + timedelta(days=2))})
    assert later.semantic_content_id == state.semantic_content_id
    assert later.production != state.production


def test_mixed_and_unavailable_snapshots_keep_field_assessments():
    valid = field()
    missing = field(field_key="power_w", value=None, validity=StateValidity.UNKNOWN,
                    evidence_refs=(), freshness_assessment="source_time_unavailable")
    partial = snapshot(valid, missing, completeness_status=SnapshotCompleteness.PARTIAL)
    assert len(partial.usable_fields) == 1 and len(partial.unavailable_fields) == 1
    assert snapshot(missing, completeness_status=SnapshotCompleteness.UNAVAILABLE).fields[0].value is None
    with pytest.raises(ValidationError, match="completeness"):
        snapshot(valid, missing, completeness_status=SnapshotCompleteness.COMPLETE)


def test_degraded_requires_rule_and_invalid_requires_positive_reason():
    with pytest.raises(ValidationError, match="versioned rule"):
        field(validity=StateValidity.DEGRADED)
    degraded = field(validity=StateValidity.DEGRADED, degradation_rule_id="limited_identity",
                     degradation_rule_version="v1", limitations=("restricted_scope",))
    assert degraded.value == 0
    with pytest.raises(ValidationError, match="failure evidence"):
        field(validity=StateValidity.INVALID, value=None)
    invalid = field(validity=StateValidity.INVALID, value=None,
                    failure_reason="identity_violation")
    assert invalid.value is None


def test_last_known_context_cannot_fill_unknown_current_value():
    old = LastKnownContext(value=12.0, observation_id=uuid4(), source_time=T - timedelta(hours=1),
                           receipt_time=T - timedelta(hours=1), age_seconds=3600,
                           age_assessment="historical")
    unknown = field(value=None, validity=StateValidity.UNKNOWN, last_known=old)
    assert unknown.value is None and unknown.last_known.value == 12.0
    with pytest.raises(ValidationError, match="value and validity"):
        field(value=0, validity=StateValidity.UNKNOWN)


def test_confidence_is_structured_support_not_quality_probability_or_freshness():
    limited = field(confidence=confidence(SupportStatus.LIMITED))
    assert limited.validity == StateValidity.VALID
    assert limited.confidence.support_status == SupportStatus.LIMITED
    with pytest.raises(ValidationError, match="all applicable checks"):
        StateConfidence(interpretation="CURRENT_ESTIMATE_SUPPORT", rubric_id="r", rubric_version="1",
                        support_status=SupportStatus.SUPPORTED,
                        support_checks=(SupportCheck(check_id="x", kind=SupportCheckKind.STRENGTHENING,
                                                     result=CheckResult.FAIL),))
    with pytest.raises(ValidationError, match="all applicable checks"):
        StateConfidence(interpretation="CURRENT_ESTIMATE_SUPPORT", rubric_id="r", rubric_version="1",
                        support_status=SupportStatus.SUPPORTED,
                        support_checks=(SupportCheck(check_id="x", kind=SupportCheckKind.STRENGTHENING,
                                                     result=CheckResult.NOT_APPLICABLE),))
    with pytest.raises(ValidationError):
        StateConfidence(interpretation="PROBABILITY", rubric_id="r", rubric_version="1",
                        support_status=SupportStatus.SUPPORTED, support_checks=())
    with pytest.raises(ValidationError, match="duplicate support check"):
        repeated = SupportCheck(check_id="same", kind=SupportCheckKind.MINIMUM, result=CheckResult.PASS)
        StateConfidence(interpretation="CURRENT_ESTIMATE_SUPPORT", rubric_id="r", rubric_version="1",
                        support_status=SupportStatus.SUPPORTED, support_checks=(repeated, repeated))
    with pytest.raises(ValidationError, match="passing minimum"):
        StateConfidence(interpretation="CURRENT_ESTIMATE_SUPPORT", rubric_id="r", rubric_version="1",
                        support_status=SupportStatus.LIMITED,
                        support_checks=(SupportCheck(check_id="minimum", kind=SupportCheckKind.MINIMUM,
                                                     result=CheckResult.FAIL),))
    with pytest.raises(ValidationError, match="strengthening check"):
        StateConfidence(interpretation="CURRENT_ESTIMATE_SUPPORT", rubric_id="r", rubric_version="1",
                        support_status=SupportStatus.LIMITED,
                        support_checks=(SupportCheck(check_id="minimum", kind=SupportCheckKind.MINIMUM,
                                                     result=CheckResult.PASS),))


def test_uncertainty_dimensions_and_quantification_boundary():
    dimensions = dict(uncertainty().dimensions)
    dimensions[UncertaintyDimension.TEMPORAL] = UncertaintyAssessment(
        status=UncertaintyStatus.KNOWN_UNQUANTIFIED, reason="source_clock_missing",
        limitations=("source_age_unknown",))
    assert StateUncertainty(dimensions=dimensions).dimensions[UncertaintyDimension.TEMPORAL].quantification is None
    with pytest.raises(ValidationError, match="numeric value"):
        UncertaintyAssessment(status=UncertaintyStatus.UNKNOWN, reason="unknown", quantification=0)
    with pytest.raises(ValidationError, match="explicit limitation"):
        UncertaintyAssessment(status=UncertaintyStatus.KNOWN_UNQUANTIFIED, reason="known")
    quantified = UncertaintyAssessment(status=UncertaintyStatus.QUANTIFIED, reason="measured",
        quantification=(1.0, 2.0), unit="degC", method_name="calibrated_interval",
        method_version="v1", assumptions=("test_assumption",))
    assert quantified.quantification == (1.0, 2.0)
    with pytest.raises(ValidationError, match="requires value"):
        UncertaintyAssessment(status=UncertaintyStatus.QUANTIFIED, reason="claim")
    with pytest.raises(ValidationError, match="reversed"):
        UncertaintyAssessment(status=UncertaintyStatus.QUANTIFIED, reason="claim",
                              quantification=(2.0, 1.0), unit="degC", method_name="method",
                              method_version="v1", assumptions=("assumption",))
    with pytest.raises(ValidationError, match="every accepted"):
        StateUncertainty(dimensions={UncertaintyDimension.METHOD: dimensions[UncertaintyDimension.METHOD]})


@pytest.mark.parametrize("changes, reason", [
    ({"required": ("x", "x")}, "duplicate evidence"),
    ({"satisfied": ("other",)}, "unknown required"),
    ({"unavailable": ("temperature",)}, "conflicting dispositions"),
    ({"optional_support": ("temperature",)}, "optional evidence"),
])
def test_evidence_completeness_rejects_forged_accounting(changes, reason):
    with pytest.raises(ValidationError, match=reason):
        EvidenceCompleteness.model_validate({**completeness().model_dump(), **changes})


def test_field_contract_requires_explicit_window_limits_and_distinct_signals():
    data = field_contract_data()
    signal = data["required_signals"][0]
    assert FieldEvidenceContract(**data).window_seconds == 30
    with pytest.raises(ValidationError):
        FieldEvidenceContract(**{k: v for k, v in data.items() if k != "window_seconds"})
    with pytest.raises(ValidationError):
        FieldEvidenceContract(**{**data, "maximum_records": 0})
    with pytest.raises(ValidationError, match="both required and optional"):
        FieldEvidenceContract(**{**data, "optional_signals": (signal,)})
    with pytest.raises(ValidationError, match="duplicate signal"):
        FieldEvidenceContract(**{**data, "required_signals": (signal, signal)})


def field_contract_data():
    signal = SignalRequirement(source="NVML", signal="temperature_c",
                               source_semantics="m3.1.nvml.temperature", unit="degC")
    return {
        "contract_id": "gpu-temperature", "contract_version": "v1", "field_key": "temperature_c",
        "estimand": "GPU temperature at reference time", "subject_scope": "gpu_uuid",
        "required_signals": (signal,), "optional_signals": (), "identity_requirements": ("gpu_uuid",),
        "allowed_units": ("degC",), "allowed_conversions": (), "admissible_quality": (Quality.VALID,),
        "temporal_basis": TimeBasis.SOURCE_OBSERVATION_TIME, "window_seconds": 30,
        "minimum_samples": 1, "minimum_span_seconds": 0, "minimum_coverage_fraction": None,
        "maximum_gap_seconds": None, "continuity_rule": "not_applicable",
        "conflict_rule": "unresolved_unknown", "permitted_degradation_rules": (),
        "confidence_rubric_id": "r", "confidence_rubric_version": "v1",
        "output_type": "number", "output_unit": "degC", "maximum_records": 100,
        "maximum_decoded_bytes": 10000, "maximum_subjects": 1, "predecessor_lookback_seconds": 0,
    }


def test_evidence_reference_preserves_null_source_identity_and_aware_clocks():
    ref = evidence()
    assert ref.source_instance == "uuid:GPU-1"
    assert ref.input_quality == Quality.VALID and ref.recorded_freshness == Freshness()
    assert StateEvidenceReference.model_validate({**ref.model_dump(), "source_instance": None}).source_instance is None
    shifted = datetime(2026, 1, 1, 3, tzinfo=timezone(timedelta(hours=3)))
    assert StateEvidenceReference.model_validate({**ref.model_dump(), "observation_time": shifted}).observation_time == T
    with pytest.raises(ValidationError):
        StateEvidenceReference.model_validate({**ref.model_dump(), "observation_time": datetime(2026, 1, 1)})
    with pytest.raises(ValidationError, match="digest or immutable"):
        StateEvidenceReference.model_validate({**ref.model_dump(), "payload_sha256": None})


def test_conflict_participants_cannot_be_silently_selected():
    participant = uuid4()
    other = uuid4()
    data = {
        "conflict_id": uuid4(), "affected_field_key": "temperature_c",
        "kind": ConflictKind.VALUE_DISAGREEMENT, "participant_evidence_ids": (participant, other),
        "comparison_contract_id": "temperature", "comparison_contract_version": "v1",
        "comparison_basis": "same_gpu_time_and_unit", "resolution_status": "UNRESOLVED",
        "reason": "different_values",
    }
    assert StateConflict(**data).participant_evidence_ids == (participant, other)
    with pytest.raises(ValidationError, match="versioned resolution rule"):
        StateConflict(**{**data, "selected_evidence_ids": (participant,)})
    with pytest.raises(ValidationError, match="nonparticipant"):
        StateConflict(**{**data, "rejected_evidence_ids": (uuid4(),)})
    with pytest.raises(ValidationError, match="duplicate conflict participant"):
        StateConflict(**{**data, "participant_evidence_ids": (participant, participant)})
    with pytest.raises(ValidationError, match="must be paired"):
        StateConflict(**{**data, "resolution_rule_id": "rule"})
    with pytest.raises(ValidationError, match="both selected and rejected"):
        StateConflict(**{**data, "resolution_rule_id": "rule", "resolution_rule_version": "v1",
                         "selected_evidence_ids": (participant,), "rejected_evidence_ids": (participant,)})
    with pytest.raises(ValidationError, match="needs a unit"):
        StateConflict(**{**data, "quantified_disagreement": 1.0})


def test_unavailable_and_supported_fields_reject_false_evidence_claims():
    with pytest.raises(ValidationError, match="assessed support"):
        field(value=None, validity=StateValidity.UNKNOWN, confidence=confidence())
    with pytest.raises(ValidationError, match="duplicate field evidence"):
        ref = evidence()
        field(evidence_refs=(ref, ref))
    with pytest.raises(ValidationError, match="supporting observation"):
        field(ref=evidence(disposition=EvidenceDisposition.CONTEXT_ONLY))
    with pytest.raises(ValidationError, match="all declared required evidence"):
        field(evidence_completeness=EvidenceCompleteness(required=("temperature",),
            satisfied=(), unavailable=("temperature",), conflicting=(), optional_support=()))
    conflict = StateConflict(conflict_id=uuid4(), affected_field_key="power_w",
                             kind=ConflictKind.VALUE_DISAGREEMENT,
                             participant_evidence_ids=(uuid4(), uuid4()),
                             comparison_contract_id="power", comparison_contract_version="v1",
                             comparison_basis="same_subject", resolution_status="UNRESOLVED",
                             reason="different_values")
    with pytest.raises(ValidationError, match="different field"):
        field(conflicts=(conflict,))
    same_field = StateConflict.model_validate({**conflict.model_dump(),
                                               "affected_field_key": "temperature_c"})
    with pytest.raises(ValidationError, match="participants must be retained"):
        field(conflicts=(same_field,))


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), {"nested": float("-inf")}])
def test_nonfinite_values_never_enter_state_contract(bad_value):
    with pytest.raises(ValidationError):
        field(value=bad_value)


def test_snapshot_rejects_forged_inventory_and_inconsistent_reference_time():
    first = field()
    with pytest.raises(ValidationError, match="duplicate field identity"):
        snapshot(first, first, completeness_status=SnapshotCompleteness.COMPLETE)
    with pytest.raises(ValidationError, match="inconsistent reference times"):
        snapshot(first, field(field_key="power_w", state_reference_time=T + timedelta(seconds=1)),
                 completeness_status=SnapshotCompleteness.COMPLETE)
    with pytest.raises(ValidationError, match="field lists disagree"):
        StateSnapshot.model_validate({**snapshot(first, completeness_status=SnapshotCompleteness.COMPLETE).model_dump(),
                                      "usable_fields": []})
    with pytest.raises(ValidationError, match="field lists disagree"):
        StateSnapshot.model_validate({**snapshot(first, completeness_status=SnapshotCompleteness.COMPLETE).model_dump(),
                                      "usable_fields": [FieldRequest(field_key=first.field_key,
                                                                     subject_scope=first.subject_scope).model_dump()] * 2})
    with pytest.raises(ValidationError, match="inventory differs"):
        StateSnapshot.model_validate({**snapshot(first, completeness_status=SnapshotCompleteness.COMPLETE).model_dump(),
                                      "requested_fields": [{"field_key": "other", "subject_scope": "uuid:GPU-1"}]})


def test_artifact_and_contract_reject_unsupported_schema_and_hidden_extra_fields():
    state = EstimatedState(state_type="gpu_current",
                           snapshot=snapshot(field(), completeness_status=SnapshotCompleteness.COMPLETE),
                           semantic_content_id=DIGEST,
                           production=ProductionMetadata(artifact_id=uuid4(), estimated_at=T))
    with pytest.raises(ValidationError):
        EstimatedState.model_validate({**state.model_dump(), "schema_version": "future"})
    with pytest.raises(ValidationError):
        EstimatedState.model_validate({**state.model_dump(), "execution_authorized": True})
    with pytest.raises(ValidationError):
        ProductionMetadata(artifact_id=state.state_id, estimated_at=datetime(2026, 1, 1))
    with pytest.raises(ValidationError, match="cannot supersede itself"):
        ProductionMetadata(artifact_id=state.state_id, estimated_at=T,
                           supersedes_artifact_id=state.state_id)
    with pytest.raises(ValidationError, match="needs a value"):
        LastKnownContext(value=None, observation_id=uuid4(), source_time=None,
                         receipt_time=T, age_seconds=None, age_assessment="unknown")


@pytest.mark.parametrize("injected", [float("nan"), float("inf"), float("-inf")])
def test_nested_content_is_immutable_and_detached_from_input_and_output(injected):
    raw_value = {"samples": [{"value": 0}]}
    raw_config = {"window": {"seconds": [30]}}
    dimensions = dict(uncertainty().dimensions)
    first = field(value=raw_value, configuration=raw_config,
                  uncertainty=StateUncertainty(dimensions=dimensions),
                  last_known=LastKnownContext(value={"old": [0]}, observation_id=uuid4(),
                      source_time=None, receipt_time=T, age_seconds=None, age_assessment="unknown"))
    state = EstimatedState(state_type="test", semantic_content_id=DIGEST,
        snapshot=snapshot(first, completeness_status=SnapshotCompleteness.COMPLETE),
        production=ProductionMetadata(artifact_id=uuid4(), estimated_at=T))
    before = state.model_dump_json()
    with pytest.raises(TypeError):
        first.value["samples"][0]["value"] = injected
    with pytest.raises(TypeError):
        first.value["samples"][0] = injected
    with pytest.raises(TypeError):
        first.configuration["window"]["seconds"][0] = -1
    with pytest.raises(TypeError):
        first.configuration["new"] = injected
    with pytest.raises(TypeError):
        del first.uncertainty.dimensions[UncertaintyDimension.TEMPORAL]
    with pytest.raises(TypeError):
        first.last_known.value["old"][0] = injected
    with pytest.raises(ValidationError):
        first.confidence.support_checks[0].result = CheckResult.FAIL
    with pytest.raises(ValidationError):
        first.uncertainty.dimensions[UncertaintyDimension.METHOD].reason = "changed"
    with pytest.raises(TypeError):
        state.snapshot.fields[0] = field(value=99)
    with pytest.raises(ValidationError):
        state.production.estimated_at = T + timedelta(days=1)
    raw_value["samples"][0]["value"] = injected
    raw_config["window"]["seconds"][0] = -1
    dimensions.clear()
    exported = state.model_dump()
    exported["snapshot"]["fields"][0]["value"]["samples"][0]["value"] = injected
    assert state.model_dump_json() == before
    assert state.semantic_content_id == DIGEST
    assert EstimatedState.model_validate_json(before) == state
    assert EstimatedStateField.model_validate({**first.model_dump(), "value": first.value}) == first
    assert field(value=(0, 1)).model_dump()["value"] == [0, 1]


def conflict_data(first, second):
    return {"conflict_id": uuid4(), "affected_field_key": "temperature_c",
        "kind": ConflictKind.VALUE_DISAGREEMENT,
        "participant_evidence_ids": (first.observation_id, second.observation_id),
        "comparison_contract_id": "comparable-temperature", "comparison_contract_version": "v1",
        "comparison_basis": "same subject, quantity, unit and eligible interval",
        "resolution_status": ConflictResolutionStatus.UNRESOLVED, "reason": "competing values"}


@pytest.mark.parametrize("validity", [StateValidity.VALID, StateValidity.DEGRADED])
def test_unresolved_comparable_conflict_cannot_retain_current_value(validity):
    first, second = evidence(), evidence(disposition=EvidenceDisposition.CONFLICTING)
    conflict = StateConflict(**conflict_data(first, second))
    with pytest.raises(ValidationError, match="unresolved comparable conflict"):
        field(validity=validity, evidence_refs=(first, second), conflicts=(conflict,),
              degradation_rule_id="cannot_hide_conflict", degradation_rule_version="v1")
    unknown = field(value=None, validity=StateValidity.UNKNOWN,
                    evidence_refs=(first, second), conflicts=(conflict,))
    assert unknown.value is None
    assert unknown.conflicts[0].participant_evidence_ids == (first.observation_id, second.observation_id)
    integrity = StateConflict(**{**conflict_data(first, second), "kind": ConflictKind.IDENTITY_MISMATCH})
    invalid = field(value=None, validity=StateValidity.INVALID, evidence_refs=(first, second),
                    conflicts=(integrity,), failure_reason="positive identity violation")
    assert invalid.conflicts[0].resolution_status == ConflictResolutionStatus.UNRESOLVED


def test_resolution_status_is_typed_and_requires_explicit_metadata():
    first, second = evidence(), evidence()
    data = conflict_data(first, second)
    for changes in (
        {"resolution_status": "pretend"},
        {"resolution_status": "resolved"},
        {"resolution_status": "RESOLVED"},
        {"resolution_status": "RESOLVED", "resolution_rule_id": " ", "resolution_rule_version": "v1"},
        {"resolution_status": "RESOLVED", "resolution_rule_id": "rule", "resolution_rule_version": " "},
        {"resolution_status": "RESOLVED", "resolution_rule_id": "rule", "resolution_rule_version": "v1", "reason": " "},
        {"participant_evidence_ids": (first.observation_id,)},
        {"resolution_rule_id": "r", "resolution_rule_version": "v1", "selected_evidence_ids": (first.observation_id,)},
        {"rejected_evidence_ids": (second.observation_id,)},
    ):
        with pytest.raises(ValidationError):
            StateConflict(**{**data, **changes})
    resolved = StateConflict(**{**data, "resolution_status": "RESOLVED",
        "resolution_rule_id": "explicit-test-rule", "resolution_rule_version": "v1",
        "selected_evidence_ids": (first.observation_id,), "rejected_evidence_ids": (second.observation_id,)})
    result = field(evidence_refs=(first, second), conflicts=(resolved,))
    restored = EstimatedStateField.model_validate_json(result.model_dump_json())
    assert restored.conflicts == (resolved,)
    assert restored.conflicts[0].selected_evidence_ids == (first.observation_id,)
    assert StateConflict(**data).selected_evidence_ids == ()


@pytest.mark.parametrize("changes", [
    {"window_seconds": -1}, {"window_seconds": 0}, {"minimum_span_seconds": -1},
    {"minimum_span_seconds": 100}, {"terminal_recency_seconds": -1},
    {"terminal_recency_seconds": 31}, {"maximum_alignment_seconds": -1},
    {"terminal_recency_seconds": float("nan")}, {"maximum_alignment_seconds": float("inf")},
])
def test_impossible_temporal_configuration_is_rejected(changes):
    with pytest.raises(ValidationError):
        FieldEvidenceContract(**{**field_contract_data(), **changes})


def test_temporal_requirements_round_trip_without_hidden_thresholds():
    absent = FieldEvidenceContract(**field_contract_data())
    assert absent.terminal_recency_seconds is None and absent.maximum_alignment_seconds is None
    for span, terminal, alignment in ((0, 0, 0), (30, 30, 2), (10, 5, 1)):
        contract = FieldEvidenceContract(**{**field_contract_data(), "minimum_span_seconds": span,
            "terminal_recency_seconds": terminal, "maximum_alignment_seconds": alignment})
        restored = FieldEvidenceContract.model_validate_json(contract.model_dump_json())
        assert restored == contract
        assert restored.window_seconds == 30
        assert restored.terminal_recency_seconds == terminal
        assert restored.maximum_alignment_seconds == alignment
    assert FieldEvidenceContract.model_validate_json(absent.model_dump_json()) == absent


@pytest.mark.parametrize("reason", ["", " ", "\t", "\n", " \t\n "])
def test_invalid_requires_nonwhitespace_failure_reason(reason):
    with pytest.raises(ValidationError, match="positive failure evidence"):
        field(validity=StateValidity.INVALID, value=None, failure_reason=reason)


def test_substantive_failure_reason_is_preserved_exactly():
    reason = " \tidentity violation: conflicting subject UUIDs\n"
    result = field(validity=StateValidity.INVALID, value=None, failure_reason=reason)
    assert result.failure_reason == reason
    assert EstimatedStateField.model_validate_json(result.model_dump_json()).failure_reason == reason


@pytest.mark.parametrize("validity", [StateValidity.VALID, StateValidity.DEGRADED])
def test_resolved_label_without_participant_outcome_cannot_support_current_field(validity):
    first, second = evidence(), evidence()
    data = {**conflict_data(first, second), "resolution_status": "RESOLVED",
            "resolution_rule_id": "caller_claim", "resolution_rule_version": "v1"}
    with pytest.raises(ValidationError, match="explicit participant outcomes"):
        StateConflict(**data)
    # Exercise nested validation too: a raw conflict cannot bypass the guard.
    with pytest.raises(ValidationError, match="explicit participant outcomes"):
        field(validity=validity, evidence_refs=(first, second), conflicts=(data,),
              degradation_rule_id="declared", degradation_rule_version="v1")


@pytest.mark.parametrize("invalid_outcome", ["unknown_selected", "unknown_rejected", "overlap"])
def test_resolved_participant_outcomes_must_be_known_and_disjoint(invalid_outcome):
    first, second = evidence(), evidence()
    outcomes = {
        "unknown_selected": {"selected_evidence_ids": (uuid4(),)},
        "unknown_rejected": {"rejected_evidence_ids": (uuid4(),)},
        "overlap": {"selected_evidence_ids": (first.observation_id,),
                    "rejected_evidence_ids": (first.observation_id,)},
    }
    with pytest.raises(ValidationError, match=r"nonparticipant|both selected and rejected"):
        StateConflict(**{**conflict_data(first, second), "resolution_status": "RESOLVED",
                         "resolution_rule_id": "declared", "resolution_rule_version": "v1",
                         **outcomes[invalid_outcome]})


@pytest.mark.parametrize("outcome", ["selected_only", "rejected_only", "partition", "multiple_selected"])
def test_explicit_resolved_outcomes_are_recorded_without_executing_a_rule(outcome):
    first, second = evidence(), evidence()
    a, b = first.observation_id, second.observation_id
    selected, rejected = {
        "selected_only": ((a,), ()), "rejected_only": ((), (b,)),
        "partition": ((a,), (b,)), "multiple_selected": ((a, b), ()),
    }[outcome]
    conflict = StateConflict(**{**conflict_data(first, second), "resolution_status": "RESOLVED",
        "resolution_rule_id": "metadata-only-test-rule", "resolution_rule_version": "v1",
        "selected_evidence_ids": selected, "rejected_evidence_ids": rejected})
    restored = StateConflict.model_validate_json(conflict.model_dump_json())
    assert restored.selected_evidence_ids == selected
    assert restored.rejected_evidence_ids == rejected
    assert restored.participant_evidence_ids == (a, b)
    assert restored == conflict
