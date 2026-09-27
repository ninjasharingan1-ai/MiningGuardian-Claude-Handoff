"""M3.2-S4-A descriptive-method tests: methods, configuration, input boundaries.

Every fixture here is a safe local fake derived from the frozen M3.1/M3.2
contracts. No test touches real hardware, a database, a provider or a miner.
"""

import ast
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from mining_guardian.observability.models import Quality, RuntimeObservation, Source
from mining_guardian.state import methods as methods_module
from mining_guardian.state.admission import AdmissionConfig, assess_admission
from mining_guardian.state.contracts import FieldEvidenceContract, TimeBasis
from mining_guardian.state.methods import (
    ADMISSION_CONTEXT_REASON,
    ADMISSION_EXCLUDED_REASON,
    CONVERSION_ROOT_LIMITATION,
    COUNTER_SCOPE_LIMITATION,
    CURRENTNESS_LIMITATION,
    IDENTITY_VIOLATION_LIMITATION,
    IDENTITY_VIOLATION_REASON,
    MISSING_FRACTION_LIMITATION,
    NON_COMPARABLE_REASON,
    NOT_AN_ENDPOINT_REASON,
    NOT_LATEST_REASON,
    OUTSIDE_SEGMENT_REASON,
    RECEIPT_ORDERING_LIMITATION,
    SELECTION_TIE_LIMITATION,
    SLOPE_DESCRIPTIVE_LIMITATION,
    SOURCE_TIME_MISSING_REASON,
    STREAM_SCOPE_REASON,
    TIED_LATEST_REASON,
    UNIT_MISMATCH_DECLARED_CONVERSION_REASON,
    UNIT_MISMATCH_REASON,
    UNRESOLVED_IDENTITY_REASON,
    UNASSIGNED_SEGMENT_REASON,
    CrossSegmentArithmeticError,
    EvidenceComparability,
    MethodConfiguration,
    MethodConfigurationError,
    MethodEvidence,
    MethodExecutionConfig,
    MethodIntegrityError,
    MethodLimitError,
    MethodName,
    MethodPreconditionError,
    MethodRequest,
    MethodResult,
    MethodScope,
    MethodVersion,
    NonFiniteError,
    NonNumericEvidenceError,
    SourceTimeIntervalError,
    UnsupportedMethodError,
    UnsupportedMethodVersionError,
    compute_candidate,
    method_configuration_digest,
    supported_method_versions,
)
from mining_guardian.state.subjects import SubjectMapping, resolve_identity
T = datetime(2026, 1, 1, tzinfo=UTC)
EXEC_CONFIG = MethodExecutionConfig(maximum_evidence=64)
ADMISSION_CONFIG = AdmissionConfig(maximum_observations=64)

MAPPING = SubjectMapping(
    mapping_id="snapshot-1", mapping_version="v1",
    subject_provenance_keys=("configured_index",),
    include_source_instance_in_subject_key=False,
    subjects={"configured_index=0": "gpu-0", "configured_index=1": "gpu-1"},
    workload_provenance_keys=("miner_workload_id",),
    workloads={"miner_workload_id=7": "workload-7"},
    algorithm_provenance_key="raw_algorithm_name",
    algorithms={"pearlhash": "pearlpow"},
)


def field_contract(**overrides: object) -> FieldEvidenceContract:
    data: dict[str, object] = {
        "contract_id": "f1", "contract_version": "v1", "field_key": "hashrate",
        "estimand": "hashrate", "subject_scope": "gpu",
        "required_signals": [{"source": Source.NVML, "signal": "hashrate",
                              "source_semantics": "rate", "unit": "H/s"}],
        "optional_signals": [], "identity_requirements": [],
        "allowed_units": ["H/s"], "allowed_conversions": [],
        "admissible_quality": [Quality.VALID],
        "temporal_basis": TimeBasis.SOURCE_OBSERVATION_TIME, "window_seconds": 300,
        "minimum_samples": 1, "minimum_span_seconds": 0, "terminal_recency_seconds": None,
        "maximum_alignment_seconds": None, "minimum_coverage_fraction": None,
        "maximum_gap_seconds": None, "continuity_rule": "rule", "conflict_rule": "rule",
        "permitted_degradation_rules": [], "confidence_rubric_id": "r",
        "confidence_rubric_version": "v1", "output_type": "number", "output_unit": "H/s",
        "maximum_records": 100, "maximum_decoded_bytes": 100000,
        "maximum_subjects": 4, "predecessor_lookback_seconds": 0,
    }
    data.update(overrides)
    return FieldEvidenceContract(**data)


CONTRACT = field_contract()
RECEIPT_CONTRACT = field_contract(
    contract_id="f-receipt", temporal_basis=TimeBasis.GUARDIAN_RECEIPT_TIME)
STALE_CONTRACT = field_contract(
    contract_id="f-stale", admissible_quality=[Quality.VALID, Quality.STALE])


def observation(index: int, *, value: object = 10.0, unit: str | None = "H/s",
                source_offset: float | None = 10.0, receipt_offset: float | None = None,
                source: Source = Source.NVML, instance: str | None = "uuid:GPU-1",
                signal: str = "hashrate", quality: Quality = Quality.VALID,
                provenance_index: int = 0) -> RuntimeObservation:
    obs = None if source_offset is None else T - timedelta(seconds=source_offset)
    if receipt_offset is None:
        ing = T if obs is None else min(obs + timedelta(seconds=1), T)
    else:
        ing = T - timedelta(seconds=receipt_offset)
    return RuntimeObservation(
        observation_id=UUID(int=index), source=source, source_instance=instance,
        signal=signal, value=value, unit=unit, observation_time=obs,
        ingestion_time=ing,
        processing_time=ing,
        correlation_id=UUID(int=1000 + index), quality=quality,
        provenance={"configured_index": provenance_index, "miner_workload_id": 7,
                    "raw_algorithm_name": "pearlhash"})


def admission_for(record: RuntimeObservation,
                 contract: FieldEvidenceContract = CONTRACT):
    return assess_admission([record], T, contract, ADMISSION_CONFIG)[0]


def evidence(index: int, *, segment_id: str | None = None,
             comparability: EvidenceComparability = EvidenceComparability.COMPARABLE,
             reason: str | None = None, contract: FieldEvidenceContract = CONTRACT,
             **obs_kwargs: object) -> MethodEvidence:
    record = observation(index, **obs_kwargs)
    return MethodEvidence(
        record=record, admission=admission_for(record, contract),
        identity=resolve_identity(record, MAPPING), segment_id=segment_id,
        comparability=comparability, comparability_reason=reason)


def config_for(method: str, version: str = "v1", params: object = None,
               contract: FieldEvidenceContract = CONTRACT) -> MethodConfiguration:
    return MethodConfiguration.create(
        method_name=method, method_version=version,
        field_contract_id=contract.contract_id,
        field_contract_version=contract.contract_version,
        configuration={} if params is None else params)


def request_for(method: str, *, params: object = None, unit: str | None = "H/s",
                basis: TimeBasis = TimeBasis.SOURCE_OBSERVATION_TIME,
                segment_id: str | None = None,
                contract: FieldEvidenceContract = CONTRACT) -> MethodRequest:
    return MethodRequest(
        configuration=config_for(method, params=params, contract=contract),
        scope=MethodScope(source=Source.NVML, source_instance="uuid:GPU-1",
                          signal="hashrate", unit=unit),
        ordering_basis=basis, segment_id=segment_id)


def execute(method: str, items: list, **req_kwargs: object) -> MethodResult:
    return compute_candidate(list(items), request_for(method, **req_kwargs), EXEC_CONFIG)


# ---------------------------------------------------------------------------
# Configuration contract
# ---------------------------------------------------------------------------

def test_configurations_are_immutable_and_digest_identified():
    cfg = config_for("arithmetic_mean")
    assert MethodConfiguration.model_validate(cfg.model_dump()).configuration_sha256 == (
        cfg.configuration_sha256)
    with pytest.raises(ValidationError):
        cfg.method_name = "median"  # type: ignore[misc]
    frozen = dict(cfg.configuration)
    frozen["declared_conversion"] = "x"
    assert "declared_conversion" not in cfg.configuration


def test_equivalent_mapping_order_yields_same_digest():
    first = method_configuration_digest(
        method_name="median", method_version="v1",
        field_contract_id=CONTRACT.contract_id,
        field_contract_version=CONTRACT.contract_version,
        configuration={"b": 2, "a": 1})
    second = method_configuration_digest(
        method_name="median", method_version="v1",
        field_contract_id=CONTRACT.contract_id,
        field_contract_version=CONTRACT.contract_version,
        configuration={"a": 1, "b": 2})
    # The median configuration surface only allows declared_conversion, so the
    # digest helper is exercised directly for order independence of mappings.
    assert first == second


def test_semantic_configuration_change_yields_different_digest():
    low = config_for("missing_fraction", params={"expected_opportunities": 4})
    high = config_for("missing_fraction", params={"expected_opportunities": 5})
    assert low.configuration_sha256 != high.configuration_sha256
    assert config_for("median").configuration_sha256 != config_for("min").configuration_sha256


def test_unsupported_method_name_is_an_explicit_typed_failure():
    with pytest.raises(UnsupportedMethodError):
        config_for("convenient_estimator")
    with pytest.raises(UnsupportedMethodError):
        config_for("LATEST_ELIGIBLE_VALUE")


def test_unsupported_method_version_is_an_explicit_typed_failure():
    with pytest.raises(UnsupportedMethodVersionError):
        config_for("median", version="v2")
    with pytest.raises(UnsupportedMethodVersionError):
        config_for("median", version="latest")


def test_missing_mandatory_configuration_is_an_explicit_failure():
    with pytest.raises(MethodConfigurationError):
        config_for("missing_fraction", params={})


def test_no_default_estimator_and_no_alias_resolution():
    versions = supported_method_versions()
    assert set(versions) == set(MethodName)
    # Unknown spellings must not resolve to a convenient neighbour.
    for alias in ("latest", "mean", "average", "rate", "slope", "count", "mode"):
        with pytest.raises(UnsupportedMethodError):
            config_for(alias)


# ---------------------------------------------------------------------------
# latest eligible observed value
# ---------------------------------------------------------------------------

def test_latest_single_eligible_value():
    result = execute("latest_eligible_value", [evidence(1, value=7.0, source_offset=4.0)])
    assert result.method_name == "latest_eligible_value"
    assert result.method_version == "v1"
    assert result.value == 7.0
    assert result.unit == "H/s"
    assert [str(i) for i in result.participants] == [str(UUID(int=1))]
    assert result.excluded == ()
    assert CURRENTNESS_LIMITATION in result.limitations


def test_latest_selects_chronological_winner_not_value_winner():
    items = [evidence(1, value=100.0, source_offset=30.0),
             evidence(2, value=1.0, source_offset=5.0)]
    result = execute("latest_eligible_value", items)
    assert result.value == 1.0
    assert [str(i) for i in result.participants] == [str(UUID(int=2))]
    reasons = {str(e.observation_id): e.reason for e in result.excluded}
    assert reasons == {str(UUID(int=1)): NOT_LATEST_REASON}


def test_latest_input_order_does_not_change_selection():
    items = [evidence(1, value=100.0, source_offset=30.0),
             evidence(2, value=1.0, source_offset=5.0)]
    assert execute("latest_eligible_value", items) == execute(
        "latest_eligible_value", list(reversed(items)))


def test_latest_tie_breaks_deterministically_by_receipt_then_identity():
    first = evidence(1, value=1.0, source_offset=10.0, receipt_offset=8.0)
    second = evidence(2, value=2.0, source_offset=10.0, receipt_offset=9.0)
    result = execute("latest_eligible_value", [first, second])
    assert result.value == 1.0
    assert [str(i) for i in result.participants] == [str(UUID(int=1))]
    assert SELECTION_TIE_LIMITATION in result.limitations
    assert result.metadata["tie_count"] == 1
    same_receipt = [evidence(4, value=4.0, source_offset=10.0, receipt_offset=9.0),
                    evidence(3, value=3.0, source_offset=10.0, receipt_offset=9.0)]
    tied = execute("latest_eligible_value", same_receipt)
    assert tied.value == 4.0
    assert [str(i) for i in tied.participants] == [str(UUID(int=4))]

# ---------------------------------------------------------------------------
# arithmetic sample mean
# ---------------------------------------------------------------------------

def test_mean_single_value():
    result = execute("arithmetic_mean", [evidence(1, value=7.0)])
    assert result.value == 7.0
    assert [str(i) for i in result.participants] == [str(UUID(int=1))]
    assert result.excluded == ()
    assert result.metadata["sample_count"] == 1


def test_mean_multiple_values_are_exact_and_unordered():
    values = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0]
    items = [evidence(index, value=value, source_offset=10.0 + index)
             for index, value in enumerate(values, start=1)]
    result = execute("arithmetic_mean", items)
    assert result.value == math.fsum(values) / len(values)


def test_mean_shuffled_input_yields_same_semantic_result():
    values = [0.1, 0.2, 0.3, 100.0, -50.0, 7.0]
    items = [evidence(index, value=value, source_offset=10.0 + index)
             for index, value in enumerate(values, start=1)]
    assert execute("arithmetic_mean", items).value == execute(
        "arithmetic_mean", list(reversed(items))).value


def test_mean_rejects_nonnumeric_and_nonfinite_evidence():
    with pytest.raises(NonNumericEvidenceError):
        execute("arithmetic_mean", [evidence(1, value="fast")])
    with pytest.raises(NonNumericEvidenceError):
        execute("arithmetic_mean", [evidence(1, value=True)])
    with pytest.raises(NonFiniteError):
        execute("arithmetic_mean", [evidence(1, value=10 ** 400)])


def test_mean_overflow_is_a_nonfinite_result_not_a_number():
    with pytest.raises(NonFiniteError):
        execute("arithmetic_mean", [evidence(1, value=1e308), evidence(2, value=1e308)])


# ---------------------------------------------------------------------------
# median
# ---------------------------------------------------------------------------

def test_median_odd_sample_count_returns_middle_value():
    items = [evidence(index, value=value, source_offset=10.0 + index)
             for index, value in enumerate((9.0, 1.0, 5.0), start=1)]
    result = execute("median", items)
    assert result.value == 5.0
    assert result.metadata["sample_count"] == 3
    assert result.metadata["even_sample_pair"] is False


def test_median_even_sample_count_returns_mean_of_two_middle_values():
    items = [evidence(index, value=value, source_offset=10.0 + index)
             for index, value in enumerate((9.0, 1.0, 5.0, 3.0), start=1)]
    result = execute("median", items)
    assert result.value == (3.0 + 5.0) / 2
    assert result.metadata["even_sample_pair"] is True


def test_median_shuffled_input_yields_same_semantic_result():
    values = [7.0, -2.0, 0.0, 100.0, 3.5]
    items = [evidence(index, value=value, source_offset=10.0 + index)
             for index, value in enumerate(values, start=1)]
    assert execute("median", items).value == execute(
        "median", list(reversed(items))).value


# ---------------------------------------------------------------------------
# min / max
# ---------------------------------------------------------------------------

def test_min_and_max_are_deterministic_extrema():
    values = [3.0, -1.0, 7.0, -1.0, 2.0]
    items = [evidence(index, value=value, source_offset=10.0 + index)
             for index, value in enumerate(values, start=1)]
    low = execute("min", items)
    high = execute("max", items)
    assert low.value == -1.0
    assert high.value == 7.0
    assert low.metadata["extremum_direction"] == "MIN"
    assert high.metadata["extremum_direction"] == "MAX"
    assert execute("min", list(reversed(items))).value == -1.0
    assert execute("max", list(reversed(items))).value == 7.0


def test_zero_is_a_valid_numeric_value_not_missing():
    result = execute("min", [evidence(1, value=0.0)])
    assert result.value == 0.0
    assert result.excluded == ()
    result = execute("max", [evidence(1, value=0.0)])
    assert result.value == 0.0


def test_min_and_max_include_negative_values():
    values = [-3.0, -9.0, -1.0]
    items = [evidence(index, value=value, source_offset=10.0 + index)
             for index, value in enumerate(values, start=1)]
    assert execute("min", items).value == -9.0
    assert execute("max", items).value == -1.0

# ---------------------------------------------------------------------------
# within-segment delta
# ---------------------------------------------------------------------------

def test_delta_same_segment_two_values_subtracts_first_from_last():
    items = [evidence(1, value=10.0, source_offset=20.0, segment_id="seg-a"),
             evidence(2, value=25.0, source_offset=10.0, segment_id="seg-a")]
    result = execute("within_segment_delta", items, segment_id="seg-a")
    assert result.value == 15.0
    assert result.metadata["segment_id"] == "seg-a"
    assert result.metadata["first_observation_id"] == str(UUID(int=1))
    assert result.metadata["last_observation_id"] == str(UUID(int=2))


def test_delta_same_segment_many_values_uses_only_first_and_last():
    items = [evidence(index, value=float(index), source_offset=50.0 - index,
                      segment_id="seg-a") for index in (1, 2, 3, 4)]
    result = execute("within_segment_delta", items, segment_id="seg-a")
    assert result.value == 3.0
    reasons = {str(e.observation_id): e.reason for e in result.excluded}
    assert reasons == {str(UUID(int=2)): NOT_AN_ENDPOINT_REASON,
                       str(UUID(int=3)): NOT_AN_ENDPOINT_REASON}


def test_delta_derives_its_segment_only_when_unambiguous():
    items = [evidence(index, value=float(index), source_offset=50.0 - index,
                      segment_id="seg-a") for index in (1, 2, 3)]
    result = execute("within_segment_delta", items)
    assert result.value == 2.0
    assert result.metadata["segment_id"] == "seg-a"


def test_delta_cross_segment_arithmetic_is_refused():
    items = [evidence(1, value=10.0, source_offset=20.0, segment_id="seg-a"),
             evidence(2, value=25.0, source_offset=10.0, segment_id="seg-b")]
    with pytest.raises(CrossSegmentArithmeticError):
        execute("within_segment_delta", items)


def test_delta_declared_segment_excludes_other_segments_without_merging():
    items = [evidence(1, value=10.0, source_offset=20.0, segment_id="seg-a"),
             evidence(2, value=25.0, source_offset=10.0, segment_id="seg-a"),
             evidence(3, value=999.0, source_offset=5.0, segment_id="seg-b")]
    result = execute("within_segment_delta", items, segment_id="seg-a")
    assert result.value == 15.0
    reasons = {str(e.observation_id): e.reason for e in result.excluded}
    assert reasons == {str(UUID(int=3)): OUTSIDE_SEGMENT_REASON}


def test_delta_negative_change_is_preserved_without_rollover_assumption():
    items = [evidence(1, value=100.0, source_offset=20.0, segment_id="seg-a"),
             evidence(2, value=90.0, source_offset=10.0, segment_id="seg-a")]
    result = execute("within_segment_delta", items, segment_id="seg-a")
    assert result.value == -10.0


def test_delta_wraps_and_counter_decreases_do_not_create_a_positive_value():
    items = [evidence(1, value=2 ** 32 - 1, source_offset=20.0, segment_id="seg-a"),
             evidence(2, value=5.0, source_offset=10.0, segment_id="seg-a")]
    result = execute("within_segment_delta", items, segment_id="seg-a")
    assert result.value == 5.0 - (2 ** 32 - 1)


# ---------------------------------------------------------------------------
# source-time counter rate
# ---------------------------------------------------------------------------

def test_rate_uses_source_time_not_receipt_time():
    items = [evidence(1, value=100.0, source_offset=20.0, receipt_offset=19.0,
                      segment_id="seg-a"),
             evidence(2, value=300.0, source_offset=10.0, receipt_offset=1.0,
                      segment_id="seg-a")]
    result = execute("source_time_counter_rate", items, segment_id="seg-a")
    assert result.value == 20.0
    assert result.metadata["elapsed_source_seconds"] == 10.0
    assert COUNTER_SCOPE_LIMITATION in result.limitations


def test_rate_receipt_only_timing_is_rejected():
    items = [evidence(1, value=100.0, source_offset=None, receipt_offset=5.0,
                      segment_id="seg-a"),
             evidence(2, value=300.0, source_offset=None, receipt_offset=1.0,
                      segment_id="seg-a")]
    with pytest.raises(MethodPreconditionError):
        execute("source_time_counter_rate", items, segment_id="seg-a")


def test_rate_zero_elapsed_source_time_is_rejected():
    items = [evidence(1, value=100.0, source_offset=10.0, receipt_offset=9.0,
                      segment_id="seg-a"),
             evidence(2, value=300.0, source_offset=10.0, receipt_offset=8.0,
                      segment_id="seg-a")]
    with pytest.raises(SourceTimeIntervalError):
        execute("source_time_counter_rate", items, segment_id="seg-a")


def test_rate_declining_source_clock_is_rejected_not_reordered():
    first = evidence(1, value=100.0, source_offset=10.0, receipt_offset=9.0,
                     segment_id="seg-a")
    second = evidence(2, value=300.0, source_offset=20.0, receipt_offset=8.0,
                      segment_id="seg-a")
    with pytest.raises(SourceTimeIntervalError):
        execute("source_time_counter_rate", [second, first], segment_id="seg-a",
                basis=TimeBasis.GUARDIAN_RECEIPT_TIME)


def test_rate_cross_segment_arithmetic_is_rejected():
    items = [evidence(1, value=100.0, source_offset=20.0, segment_id="seg-a"),
             evidence(2, value=300.0, source_offset=10.0, segment_id="seg-b")]
    with pytest.raises(CrossSegmentArithmeticError):
        execute("source_time_counter_rate", items)


def test_rate_negative_delta_is_not_clamped():
    items = [evidence(1, value=300.0, source_offset=20.0, segment_id="seg-a"),
             evidence(2, value=100.0, source_offset=10.0, segment_id="seg-a")]
    result = execute("source_time_counter_rate", items, segment_id="seg-a")
    assert result.value == -20.0




# ---------------------------------------------------------------------------
# historical endpoint slope
# ---------------------------------------------------------------------------

def test_slope_valid_historical_endpoints():
    items = [evidence(1, value=100.0, source_offset=20.0, segment_id="seg-a"),
             evidence(2, value=300.0, source_offset=10.0, segment_id="seg-a")]
    result = execute("historical_endpoint_slope", items, segment_id="seg-a")
    assert result.value == 20.0
    assert result.metadata["elapsed_seconds"] == 10.0
    assert SLOPE_DESCRIPTIVE_LIMITATION in result.limitations


def test_slope_zero_elapsed_time_is_rejected():
    items = [evidence(1, value=100.0, source_offset=10.0, segment_id="seg-a"),
             evidence(2, value=300.0, source_offset=10.0, segment_id="seg-a")]
    with pytest.raises(SourceTimeIntervalError):
        execute("historical_endpoint_slope", items, segment_id="seg-a")


def test_slope_is_descriptive_and_never_extrapolates_or_predicts():
    items = [evidence(1, value=100.0, source_offset=20.0, segment_id="seg-a"),
             evidence(2, value=300.0, source_offset=10.0, segment_id="seg-a")]
    result = execute("historical_endpoint_slope", items, segment_id="seg-a")
    assert result.metadata["first_observation_id"] == str(UUID(int=1))
    assert result.metadata["last_observation_id"] == str(UUID(int=2))
    assert SLOPE_DESCRIPTIVE_LIMITATION in result.limitations
    assert result.metadata["elapsed_seconds"] == 10.0
    assert "predicted_value" not in result.metadata
    assert not hasattr(result, "prediction")
    assert not hasattr(result, "forecast")
    assert "forecast" not in " ".join(result.limitations)
    source = Path(methods_module.__file__).read_text(encoding="utf-8")
    assert "forecast(" not in source.lower()
    assert "def predict" not in source.lower()
    assert "extrapolat" not in source.lower()


# ---------------------------------------------------------------------------
# missing fraction
# ---------------------------------------------------------------------------

def test_missing_fraction_valid_explicit_denominator():
    items = [evidence(1, value=10.0, source_offset=10.0),
             evidence(2, value=11.0, source_offset=9.0)]
    result = execute("missing_fraction", items,
                     params={"expected_opportunities": 4})
    assert result.value == 0.5
    assert result.unit is None
    assert result.metadata["expected_opportunities"] == 4
    assert result.metadata["observed_opportunities"] == 2
    assert result.metadata["missing_opportunities"] == 2
    assert MISSING_FRACTION_LIMITATION in result.limitations


def test_missing_fraction_zero_denominator_is_rejected_at_configuration():
    with pytest.raises(MethodConfigurationError):
        config_for("missing_fraction", params={"expected_opportunities": 0})


def test_missing_fraction_missing_denominator_is_rejected_at_configuration():
    with pytest.raises(MethodConfigurationError):
        request_for("missing_fraction")


def test_missing_fraction_exact_zero_fraction():
    items = [evidence(index, value=10.0, source_offset=10.0 + index) for index in (1, 2)]
    result = execute("missing_fraction", items, params={"expected_opportunities": 2})
    assert result.value == 0.0
    assert result.metadata["missing_opportunities"] == 0


def test_missing_fraction_exact_one_fraction_needs_no_observed_evidence():
    result = execute("missing_fraction", [], params={"expected_opportunities": 4})
    assert result.value == 1.0
    assert result.participants == ()

# ---------------------------------------------------------------------------
# identity mismatch / non-comparability boundary
# ---------------------------------------------------------------------------

def test_excluded_and_not_compared_evidence_never_supports_a_method():
    items = [evidence(1, value=10.0, source_offset=20.0),
             evidence(2, value=12.0, source_offset=10.0,
                      comparability=EvidenceComparability.NON_COMPARABLE,
                      reason="identity_mismatch_excluded"),
             evidence(3, value=14.0, source_offset=5.0)]
    result = execute("arithmetic_mean", items)
    assert result.value == 12.0
    reasons = {str(e.observation_id): e.reason for e in result.excluded}
    assert reasons == {str(UUID(int=2)): NON_COMPARABLE_REASON}
    assert IDENTITY_VIOLATION_LIMITATION not in result.limitations


def test_surviving_eligible_subset_remains_usable_after_exclusions():
    stale = evidence(1, value=100.0, source_offset=10.0, contract=STALE_CONTRACT,
                     quality=Quality.STALE)
    stale_request = request_for("arithmetic_mean", contract=STALE_CONTRACT)
    items = [stale, evidence(2, value=10.0, source_offset=20.0, contract=STALE_CONTRACT),
             evidence(3, value=20.0, source_offset=10.0, contract=STALE_CONTRACT)]
    result = compute_candidate(list(items), stale_request, EXEC_CONFIG)
    assert result.value == 15.0
    reasons = {str(e.observation_id): e.reason for e in result.excluded}
    assert reasons == {str(UUID(int=1)): ADMISSION_CONTEXT_REASON}


def test_positive_identity_integrity_violation_is_distinct_from_non_comparability():
    items = [evidence(1, value=10.0, source_offset=20.0),
             evidence(2, value=1.0e9, source_offset=5.0,
                      comparability=EvidenceComparability.IDENTITY_VIOLATION,
                      reason="positive_identity_violation")]
    result = execute("arithmetic_mean", items)
    assert result.value == 10.0
    reasons = {str(e.observation_id): e.reason for e in result.excluded}
    assert reasons == {str(UUID(int=2)): IDENTITY_VIOLATION_REASON}
    assert IDENTITY_VIOLATION_LIMITATION in result.limitations


def test_unresolved_subject_identity_never_supports_a_method():
    items = [evidence(1, value=10.0, source_offset=20.0),
             evidence(2, value=12.0, source_offset=10.0, provenance_index=99)]
    result = execute("arithmetic_mean", items)
    assert result.value == 10.0
    reasons = {str(e.observation_id): e.reason for e in result.excluded}
    assert reasons == {str(UUID(int=2)): UNRESOLVED_IDENTITY_REASON}


def test_distinct_resolved_scopes_are_never_merged_without_a_winner():
    items = [evidence(1, value=10.0, source_offset=20.0, provenance_index=0),
             evidence(2, value=12.0, source_offset=10.0, provenance_index=1)]
    with pytest.raises(MethodPreconditionError):
        execute("arithmetic_mean", items)


# ---------------------------------------------------------------------------
# unit / conversion boundary
# ---------------------------------------------------------------------------

def test_incompatible_undeclared_unit_is_excluded_without_conversion():
    items = [evidence(1, value=10.0, source_offset=20.0, unit="H/s"),
             evidence(2, value=12.0, source_offset=10.0, unit="kH/s")]
    result = execute("arithmetic_mean", items, unit="H/s")
    assert result.value == 10.0
    reasons = {str(e.observation_id): e.reason for e in result.excluded}
    assert reasons == {str(UUID(int=2)): UNIT_MISMATCH_REASON}
    assert CONVERSION_ROOT_LIMITATION not in result.limitations


def test_explicit_declared_conversion_does_not_bypass_other_preconditions():
    params = {"declared_conversion": {"conversion_id": "kh", "conversion_version": "v1",
                                      "source_unit": "kH/s", "target_unit": "H/s"}}
    items = [evidence(1, value=10.0, source_offset=20.0, unit="H/s"),
             evidence(2, value=12.0, source_offset=10.0, unit="kH/s")]
    result = execute("arithmetic_mean", items, unit="H/s", params=params)
    assert result.value == 10.0
    reasons = {str(e.observation_id): e.reason for e in result.excluded}
    assert reasons == {str(UUID(int=2)): UNIT_MISMATCH_DECLARED_CONVERSION_REASON}
    assert CONVERSION_ROOT_LIMITATION in result.limitations
    stale = evidence(3, value=11.0, source_offset=5.0, contract=STALE_CONTRACT,
                     quality=Quality.STALE)
    stale_request = request_for("arithmetic_mean", unit="H/s", params=params,
                                contract=STALE_CONTRACT)
    converted = [evidence(1, value=10.0, source_offset=20.0, unit="H/s",
                          contract=STALE_CONTRACT),
                 evidence(2, value=12.0, source_offset=10.0, unit="kH/s",
                          contract=STALE_CONTRACT)]
    result = compute_candidate([*converted, stale], stale_request, EXEC_CONFIG)
    reasons = {str(e.observation_id): e.reason for e in result.excluded}
    assert reasons[str(UUID(int=2))] == UNIT_MISMATCH_DECLARED_CONVERSION_REASON
    assert reasons[str(UUID(int=3))] == ADMISSION_CONTEXT_REASON

# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------

def test_repeated_runs_and_shuffled_unordered_inputs_agree():
    values = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0]
    items = [evidence(index, value=value, source_offset=10.0 + index)
             for index, value in enumerate(values, start=1)]
    for method in ("arithmetic_mean", "median", "min", "max",
                   "latest_eligible_value", "missing_fraction"):
        kwargs = {"params": {"expected_opportunities": 8}} if method == "missing_fraction" else {}
        first = execute(method, items, **kwargs)
        second = execute(method, items, **kwargs)
        assert first == second
        assert first.model_dump() == second.model_dump()
    mean = execute("arithmetic_mean", items)
    assert mean.value == execute("arithmetic_mean", list(reversed(items))).value
    median = execute("median", items)
    assert median.value == execute("median", list(reversed(items))).value


def test_mutable_caller_config_cannot_mutate_validated_configuration():
    caller = {"expected_opportunities": 4}
    cfg = config_for("missing_fraction", params=caller)
    digest = cfg.configuration_sha256
    caller["expected_opportunities"] = 999
    caller["injected"] = 1
    result = compute_candidate(
        [evidence(1, value=10.0, source_offset=10.0)],
        request_for("missing_fraction", params={"expected_opportunities": 4}),
        EXEC_CONFIG)
    assert result.value == 0.75
    assert cfg.configuration_sha256 == digest
    assert dict(cfg.configuration) == {"expected_opportunities": 4}


def test_method_results_carry_no_wall_clock_or_randomness_dependency():
    first = execute("arithmetic_mean", [evidence(1, value=10.0, source_offset=10.0),
                                        evidence(2, value=20.0, source_offset=5.0)])
    second = execute("arithmetic_mean", [evidence(1, value=10.0, source_offset=10.0),
                                         evidence(2, value=20.0, source_offset=5.0)])
    assert first == second
    import re

    source = Path(methods_module.__file__).read_text(encoding="utf-8")
    for token in ("datetime.now", "utcnow", "time.time", "random.",
                  "os.urandom"):
        assert token not in source
    assert "uuid4(" not in source
    assert not re.search(r"(?<![\w.\"'])hash\(", source)


# ---------------------------------------------------------------------------
# non-finite rejection
# ---------------------------------------------------------------------------

def test_nan_and_signed_infinity_inputs_are_rejected_not_coerced():
    for bad in (float("nan"), float("inf"), float("-inf")):
        record = observation(1, value=10.0, source_offset=10.0)
        object.__setattr__(record, "value", bad)
        item = MethodEvidence(record=record, admission=admission_for(record),
                              identity=resolve_identity(record, MAPPING))
        with pytest.raises((NonFiniteError, MethodIntegrityError)):
            execute("arithmetic_mean", [item])


def test_arithmetic_producing_a_nonfinite_output_is_rejected():
    items = [evidence(1, value=1e308, source_offset=20.0),
             evidence(2, value=1e308, source_offset=10.0)]
    with pytest.raises(NonFiniteError):
        execute("arithmetic_mean", items)


# ---------------------------------------------------------------------------
# scope isolation
# ---------------------------------------------------------------------------

def test_state_methods_module_has_no_forbidden_side_effect_surface():
    source = Path(methods_module.__file__).read_text(encoding="utf-8")
    for token in ("sqlite3", "mining_guardian.storage", "mining_guardian.adapters",
                  "NVMLClient", "SRBMinerClient", "UnMineableClient", "AIAdvisor",
                  "subprocess", "os.system", "popen", "threading", "socket",
                  "openai", "requests.", "httpx", ".price", "payout", "wallet"):
        assert token not in source, token
    assert "StateSnapshot(" not in source
    assert "EstimatedState(" not in source
    assert "ProductionMetadata(" not in source
    assert "StateValidity" not in source
    for name in ("StateSnapshot", "EstimatedState", "ProductionMetadata", "StateValidity"):
        assert not hasattr(methods_module, name), name


def test_method_result_carries_no_final_validity_or_snapshot_shape():
    result = execute("arithmetic_mean", [evidence(1, value=10.0, source_offset=10.0)])
    assert set(type(result).model_fields) == {"method_name", "method_version",
                                              "field_contract_id", "field_contract_version",
                                              "configuration_sha256", "value", "unit",
                                              "participants", "excluded", "metadata",
                                              "limitations"}
