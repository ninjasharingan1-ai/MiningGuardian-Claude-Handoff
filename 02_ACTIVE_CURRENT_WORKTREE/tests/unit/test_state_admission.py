"""M3.2-S3-B temporal-admission tests: explicit T, exact windows, distinct clocks."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from mining_guardian.observability.models import Freshness, Quality, RuntimeObservation, Source
from mining_guardian.state.admission import (
    AdmissionAssessment,
    AdmissionConfig,
    AdmissionError,
    AdmissionFlag,
    AdmissionIntegrityError,
    AdmissionLimitError,
    AdmissionOutcome,
    PROCESSING_TIME_LIMITATION,
    RECEIPT_BASIS_LIMITATION,
    admission_window,
    assess_admission,
)
from mining_guardian.state.contracts import FieldEvidenceContract, TimeBasis

T = datetime(2026, 1, 1, tzinfo=UTC)
CONFIG = AdmissionConfig(maximum_observations=64)


def contract(**changes) -> FieldEvidenceContract:
    data = {
        "contract_id": "temperature", "contract_version": "v1", "field_key": "temperature_c",
        "estimand": "latest_eligible_value", "subject_scope": "gpu-0",
        "required_signals": [{"source": "NVML", "signal": "temperature_c",
                              "source_semantics": "device_temperature", "unit": "degC"}],
        "optional_signals": [], "identity_requirements": [], "allowed_units": ["degC"],
        "allowed_conversions": [], "admissible_quality": [Quality.VALID],
        "temporal_basis": TimeBasis.SOURCE_OBSERVATION_TIME,
        "window_seconds": 30, "minimum_samples": 1, "minimum_span_seconds": 0,
        "terminal_recency_seconds": None, "maximum_alignment_seconds": None,
        "minimum_coverage_fraction": None, "maximum_gap_seconds": None,
        "continuity_rule": "monotonic_source_time", "conflict_rule": "no_winner",
        "permitted_degradation_rules": [], "confidence_rubric_id": "rubric",
        "confidence_rubric_version": "v1", "output_type": "float", "output_unit": "degC",
        "maximum_records": 100, "maximum_decoded_bytes": 100_000, "maximum_subjects": 4,
        "predecessor_lookback_seconds": 0,
    }
    data.update(changes)
    return FieldEvidenceContract(**data)


def observation(**changes) -> RuntimeObservation:
    data = {
        "source": Source.NVML, "source_instance": "uuid:GPU-1", "signal": "temperature_c",
        "value": 50, "unit": "degC", "observation_time": T - timedelta(seconds=5),
        "ingestion_time": T - timedelta(seconds=4), "processing_time": T - timedelta(seconds=3),
        "correlation_id": uuid4(), "quality": Quality.VALID,
    }
    data.update(changes)
    return RuntimeObservation(**data)


def assess(record: RuntimeObservation, **changes) -> AdmissionAssessment:
    changes.setdefault("reference", T)
    changes.setdefault("contract_changes", {})
    return assess_admission([record], changes["reference"],
                            contract(**changes["contract_changes"]), CONFIG)[0]


@pytest.mark.parametrize("observation_offset,ingestion_offset,outcome,flag", [
    (-30, -29, AdmissionOutcome.EXCLUDED, AdmissionFlag.SOURCE_TIME_AT_OR_BEFORE_WINDOW_START),
    (-29.999, -28, AdmissionOutcome.ELIGIBLE, None),
    (-5, -4, AdmissionOutcome.ELIGIBLE, None),
    (0, 0, AdmissionOutcome.ELIGIBLE, None),
])
def test_exact_temporal_boundaries_are_inclusive_at_t_and_exclusive_at_window_start(
        observation_offset, ingestion_offset, outcome, flag):
    result = assess(observation(observation_time=T + timedelta(seconds=observation_offset),
                                ingestion_time=T + timedelta(seconds=ingestion_offset)))
    assert result.outcome == outcome
    assert result.window_start == T - timedelta(seconds=30)
    assert result.window_end == T
    if flag is not None:
        assert flag in result.flags


def test_evidence_received_after_t_cannot_support_the_as_of_state():
    result = assess(observation(observation_time=T - timedelta(seconds=5),
                                ingestion_time=T + timedelta(seconds=1),
                                processing_time=T + timedelta(seconds=2)))
    assert result.outcome == AdmissionOutcome.EXCLUDED
    assert AdmissionFlag.RECEIVED_AFTER_REFERENCE_TIME in result.flags
    assert AdmissionFlag.CANONICALIZED_AFTER_REFERENCE_TIME in result.flags
    assert result.receipt_age_seconds == -1.0
    assert result.eligible_for_current is False


def test_future_source_time_is_excluded_and_never_clamped_fresh():
    result = assess(observation(observation_time=T + timedelta(seconds=5),
                                ingestion_time=T + timedelta(seconds=6)))
    assert result.outcome == AdmissionOutcome.EXCLUDED
    assert AdmissionFlag.SOURCE_TIME_AFTER_REFERENCE_TIME in result.flags
    assert result.source_age_seconds == -5.0
    assert result.eligible_for_current is False


def test_source_clock_ahead_of_receipt_is_an_inconsistent_clock_not_a_fresh_value():
    result = assess(observation(observation_time=T - timedelta(seconds=1),
                                ingestion_time=T - timedelta(seconds=5)))
    assert result.outcome == AdmissionOutcome.EXCLUDED
    assert AdmissionFlag.SOURCE_CLOCK_AFTER_RECEIPT in result.flags
    assert result.source_age_seconds == 1.0


def test_unknown_processing_time_does_not_prove_historical_consumption():
    result = assess(observation(processing_time=None))
    assert result.outcome == AdmissionOutcome.ELIGIBLE
    assert AdmissionFlag.PROCESSING_TIME_UNKNOWN in result.flags
    assert PROCESSING_TIME_LIMITATION in result.limitations


def test_receipt_only_evidence_is_context_only_under_a_source_time_contract():
    result = assess(observation(observation_time=None))
    assert result.outcome == AdmissionOutcome.CONTEXT_ONLY
    assert AdmissionFlag.SOURCE_CLOCK_UNAVAILABLE in result.flags
    assert result.source_age_seconds is None
    assert result.physical_age_known is False
    assert result.eligible_for_current is False
    assert result.eligible_for_history is False
    assert RECEIPT_BASIS_LIMITATION in result.limitations


def test_receipt_basis_admits_receipt_only_evidence_with_an_explicit_limitation():
    result = assess(observation(observation_time=None),
                    contract_changes={"temporal_basis": TimeBasis.GUARDIAN_RECEIPT_TIME})
    assert result.outcome == AdmissionOutcome.ELIGIBLE
    assert result.physical_age_known is False
    assert result.source_age_seconds is None
    assert RECEIPT_BASIS_LIMITATION in result.limitations
    assert "receipt_time_is_not_a_source_event_interval" in result.limitations


def test_stale_only_evidence_cannot_populate_a_current_value_but_stays_historical():
    result = assess(observation(quality_conditions=(Quality.STALE,)),
                    contract_changes={"admissible_quality": [Quality.VALID, Quality.STALE]})
    assert result.outcome == AdmissionOutcome.CONTEXT_ONLY
    assert AdmissionFlag.STALE_RECORDED in result.flags
    assert result.eligible_for_current is False
    assert result.eligible_for_history is True


def test_missing_evidence_is_distinct_from_stale_evidence_and_from_zero():
    missing = assess(observation(value=None))
    zero = assess(observation(value=0))
    assert missing.outcome == AdmissionOutcome.EXCLUDED
    assert AdmissionFlag.VALUE_MISSING in missing.flags
    assert AdmissionFlag.STALE_RECORDED not in missing.flags
    assert zero.outcome == AdmissionOutcome.ELIGIBLE
    assert AdmissionFlag.VALUE_MISSING not in zero.flags


def test_source_failure_is_excluded_without_becoming_disagreement_or_staleness():
    result = assess(observation(quality=Quality.SOURCE_UNAVAILABLE),
                    contract_changes={"admissible_quality": [Quality.VALID, Quality.SOURCE_UNAVAILABLE]})
    assert result.outcome == AdmissionOutcome.EXCLUDED
    assert AdmissionFlag.SOURCE_UNAVAILABLE in result.flags
    assert AdmissionFlag.STALE_RECORDED not in result.flags


def test_recorded_m3_1_quality_and_freshness_are_preserved_verbatim():
    recorded = Freshness(state="CURRENT", evaluated_at=T, basis="source_observation_time",
                         age_seconds=5.0, reason="configured_source_signal_age")
    record = observation(quality=Quality.DELAYED, quality_conditions=(Quality.DELAYED,),
                         freshness=recorded, ingestion_time=T - timedelta(seconds=4),
                         observation_time=T - timedelta(seconds=5))
    result = assess(record, contract_changes={"admissible_quality": [Quality.VALID, Quality.DELAYED]})
    assert result.input_quality == record.quality
    assert result.input_quality_conditions == record.quality_conditions
    assert result.recorded_freshness == recorded
    assert result.input_quality == Quality.DELAYED
    assert result.outcome == AdmissionOutcome.ELIGIBLE


def test_every_secondary_quality_condition_is_admission_relevant():
    result = assess(observation(quality_conditions=(Quality.OUT_OF_RANGE,),
                                quality_metadata={"range": "implausible"}))
    assert result.outcome == AdmissionOutcome.EXCLUDED
    assert AdmissionFlag.QUALITY_NOT_ADMISSIBLE in result.flags


def test_assessment_cannot_claim_an_outcome_that_its_own_flags_contradict():
    with pytest.raises(ValidationError, match="disagrees with recorded flags"):
        AdmissionAssessment(
            observation_id=UUID(int=1), outcome=AdmissionOutcome.ELIGIBLE,
            flags=(AdmissionFlag.VALUE_MISSING,), reasons=("declared",),
            temporal_basis=TimeBasis.SOURCE_OBSERVATION_TIME,
            window_start=T - timedelta(seconds=30), window_end=T,
            source_age_seconds=1.0, receipt_age_seconds=1.0, physical_age_known=True,
            eligible_for_current=True, eligible_for_history=True, input_quality=Quality.VALID,
            input_quality_conditions=(Quality.VALID,), recorded_freshness=Freshness(),
            field_contract_id="temperature", field_contract_version="v1")
    with pytest.raises(ValidationError, match="current eligibility"):
        AdmissionAssessment(
            observation_id=UUID(int=1), outcome=AdmissionOutcome.EXCLUDED,
            flags=(AdmissionFlag.VALUE_MISSING,), reasons=("declared",),
            temporal_basis=TimeBasis.SOURCE_OBSERVATION_TIME,
            window_start=T - timedelta(seconds=30), window_end=T, source_age_seconds=1.0,
            receipt_age_seconds=1.0, physical_age_known=True, eligible_for_current=True,
            eligible_for_history=False, input_quality=Quality.VALID,
            input_quality_conditions=(Quality.VALID,), recorded_freshness=Freshness(),
            field_contract_id="temperature", field_contract_version="v1")


def test_admission_is_deterministic_and_independent_of_input_order():
    records = [observation(observation_id=UUID(int=index),
                           observation_time=T - timedelta(seconds=index),
                           ingestion_time=T - timedelta(seconds=index - 1))
               for index in range(1, 6)]
    forward = assess_admission(records, T, contract(), CONFIG)
    backward = assess_admission(list(reversed(records)), T, contract(), CONFIG)
    assert forward == backward
    assert [item.observation_id for item in forward] == sorted(
        (UUID(int=index) for index in range(1, 6)), key=str)
    assert len(forward) == len(records)


def test_admission_is_bounded_and_refuses_duplicate_evidence_identity():
    records = [observation(observation_id=UUID(int=index)) for index in range(1, 4)]
    with pytest.raises(AdmissionLimitError):
        assess_admission(records, T, contract(), AdmissionConfig(maximum_observations=2))
    duplicated = [observation(observation_id=UUID(int=1)), observation(observation_id=UUID(int=1))]
    with pytest.raises(AdmissionIntegrityError, match="duplicate evidence identity"):
        assess_admission(duplicated, T, contract(), CONFIG)


@pytest.mark.parametrize("reference", [
    datetime(2026, 1, 1),                       # naive wall time
    T.replace(tzinfo=None),
    "2026-01-01T00:00:00+00:00",
])
def test_naive_or_invalid_reference_instants_are_refused(reference):
    with pytest.raises(AdmissionError):
        assess_admission([observation()], reference, contract(), CONFIG)


def test_poisoned_or_mutated_window_configuration_is_refused():
    with pytest.raises(AdmissionError):
        assess_admission([observation()], T, contract(window_seconds=1e300), CONFIG)
    mutated = contract().model_copy(update={"window_seconds": -1})
    with pytest.raises(AdmissionIntegrityError):
        assess_admission([observation()], T, mutated, CONFIG)
    non_finite = contract().model_copy(update={"window_seconds": float("inf")})
    with pytest.raises(AdmissionIntegrityError):
        assess_admission([observation()], T, non_finite, CONFIG)


def test_admission_window_helper_reports_the_declared_interval():
    window_start, window_end = admission_window(T, contract(window_seconds=45))
    assert window_end == T
    assert (T - window_start).total_seconds() == 45


def test_duplicate_flooding_does_not_alter_other_assessments():
    unique = observation(observation_id=UUID(int=1))
    flood = [observation(observation_id=UUID(int=100 + index), value=50,
                         observation_time=T - timedelta(seconds=5),
                         ingestion_time=T - timedelta(seconds=4)) for index in range(20)]
    alone = assess_admission([unique], T, contract(), CONFIG)
    flooded = assess_admission([unique, *flood], T, contract(), CONFIG)
    assert flooded[0] == alone[0]
    assert len(flooded) == 21

