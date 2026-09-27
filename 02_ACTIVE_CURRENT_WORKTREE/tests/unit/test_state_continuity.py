"""M3.2-S3-C continuity-segmentation tests: boundaries, provenance, arithmetic scope."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from mining_guardian.observability.models import Quality, RuntimeObservation, Source
from mining_guardian.state import continuity as continuity_module
from mining_guardian.state.continuity import (
    BreakReason,
    ContinuityConfig,
    ContinuityContract,
    ContinuityIntegrityError,
    ContinuityLimitError,
    CounterSemantics,
    CrossSegmentError,
    IncarnationStatus,
    ScopedObservation,
    segment_evidence,
    segment_index,
    require_shared_segment,
)
from mining_guardian.state.contracts import TimeBasis
from mining_guardian.state.subjects import SubjectMapping, resolve_identity

T = datetime(2026, 1, 1, tzinfo=UTC)
CONFIG = ContinuityConfig(maximum_observations=64)

MAPPING = SubjectMapping(
    mapping_id="snapshot-1", mapping_version="v1",
    subject_provenance_keys=("configured_index",), include_source_instance_in_subject_key=False,
    subjects={"configured_index=0": "gpu-0", "configured_index=1": "gpu-1"},
    workload_provenance_keys=("miner_workload_id",),
    workloads={"miner_workload_id=7": "workload-7", "miner_workload_id=8": "workload-8"},
    algorithm_provenance_key="raw_algorithm_name",
    algorithms={"pearlhash": "pearlpow", "pearlpow": "pearlpow", "otherhash": "otheralgo"},
)


def sample(index: int, offset: float, **changes) -> RuntimeObservation:
    data = {
        "observation_id": UUID(int=index), "source": Source.NVML,
        "source_instance": "uuid:GPU-1", "signal": "accepted_shares",
        "value": 100 * index, "unit": "count",
        "observation_time": T + timedelta(seconds=offset),
        "ingestion_time": T + timedelta(seconds=offset),
        "correlation_id": uuid4(), "quality": Quality.VALID,
        "provenance": {"configured_index": 0, "miner_workload_id": 7,
                       "raw_algorithm_name": "pearlhash"},
    }
    data.update(changes)
    return RuntimeObservation(**data)


def contract(**changes) -> ContinuityContract:
    data = {
        "contract_id": "shares", "contract_version": "v1",
        "continuity_rule": "cumulative_counter_monotonic",
        "ordering_basis": TimeBasis.SOURCE_OBSERVATION_TIME,
        "maximum_gap_seconds": 60.0, "counter_semantics": CounterSemantics.CUMULATIVE,
        "honor_recorded_discontinuity": False,
        "minimum_segment_samples": 2, "minimum_segment_elapsed_seconds": 0.0,
    }
    data.update(changes)
    return ContinuityContract(**data)


def run(records, *, incarnations=None, contract_changes=None, config=CONFIG, snapshot=MAPPING):
    incarnations = incarnations if incarnations is not None else [None] * len(records)
    items = [ScopedObservation(record=record, identity=resolve_identity(record, snapshot),
                               incarnation=incarnation)
             for record, incarnation in zip(records, incarnations, strict=True)]
    return segment_evidence(items, contract(**(contract_changes or {})), config)


def reasons(result, index: int) -> tuple[BreakReason, ...]:
    return result.boundaries[index].reasons


def test_single_stream_forms_one_segment_with_complete_provenance():
    result = run([sample(1, 0), sample(2, 10), sample(3, 20)])
    assert len(result.segments) == 1
    segment = result.segments[0]
    assert segment.boundary.reasons == (BreakReason.SEGMENT_START,)
    assert segment.boundary.previous_observation_id is None
    assert segment.boundary.restart_asserted is False
    assert segment.anchor_observation_id == UUID(int=1)
    assert segment.observation_ids == (UUID(int=1), UUID(int=2), UUID(int=3))
    assert segment.ordering_basis == TimeBasis.SOURCE_OBSERVATION_TIME
    assert (segment.source, segment.source_instance, segment.signal) == (
        Source.NVML, "uuid:GPU-1", "accepted_shares")
    assert (segment.subject_id, segment.workload_id, segment.algorithm_id) == (
        "gpu-0", "workload-7", "pearlpow")
    assert segment.elapsed_seconds == 20.0
    assert segment.segment_index == 0
    assert len(segment.segment_id) == 64
    assert segment.continuity_rule == "cumulative_counter_monotonic"
    assert segment.method_version == "v1"
    assert segment.evidence_sufficient_for_derivation is True
    assert segment.incarnation_status == IncarnationStatus.UNKNOWN
    assert segment.proven_incarnation is None
    assert result.unassigned == ()


def test_counter_decrease_breaks_the_segment_without_asserting_a_restart():
    result = run([sample(1, 0, value=10), sample(2, 10, value=20),
                  sample(3, 20, value=5), sample(4, 30, value=7)])
    assert len(result.segments) == 2
    assert reasons(result, 1) == (BreakReason.COUNTER_DECREASE_OR_RESET,)
    boundary = result.boundaries[1]
    assert boundary.previous_observation_id == UUID(int=2)
    assert boundary.observation_id == UUID(int=3)
    assert boundary.elapsed_seconds == 10.0
    assert boundary.restart_asserted is False
    assert boundary.evidence == ("cumulative_value_decreased_does_not_prove_restart",)
    assert result.segments[0].observation_ids == (UUID(int=1), UUID(int=2))
    assert result.segments[1].observation_ids == (UUID(int=3), UUID(int=4))
    assert result.segments[1].proven_incarnation is None
    assert result.segments[1].incarnation_status == IncarnationStatus.UNKNOWN


def test_uptime_decrease_is_recorded_as_a_counter_reset_not_a_restart():
    result = run([sample(1, 0, signal="uptime_seconds", unit="s", value=3600.0),
                  sample(2, 10, signal="uptime_seconds", unit="s", value=10.0)])
    assert len(result.segments) == 2
    assert reasons(result, 1) == (BreakReason.COUNTER_DECREASE_OR_RESET,)
    assert all(boundary.restart_asserted is False for boundary in result.boundaries)
    assert all(segment.proven_incarnation is None for segment in result.segments)


def test_explicit_incarnation_change_breaks_and_is_the_only_proven_incarnation_path():
    stable = run([sample(1, 0), sample(2, 10)], incarnations=["inc-a", "inc-a"])
    assert len(stable.segments) == 1
    assert stable.segments[0].incarnation_status == IncarnationStatus.PROVEN
    assert stable.segments[0].proven_incarnation == "inc-a"
    changed = run([sample(1, 0), sample(2, 10), sample(3, 20)],
                  incarnations=["inc-a", "inc-a", "inc-b"])
    assert [reasons(changed, index) for index in (0, 1)] == [
        (BreakReason.SEGMENT_START,), (BreakReason.EXPLICIT_INCARNATION_CHANGE,)]
    assert [segment.proven_incarnation for segment in changed.segments] == ["inc-a", "inc-b"]


def test_unproven_or_partial_incarnation_evidence_stays_unknown():
    unknown = run([sample(1, 0), sample(2, 10)], incarnations=[None, None])
    assert unknown.segments[0].incarnation_status == IncarnationStatus.UNKNOWN
    assert unknown.segments[0].proven_incarnation is None
    partial = run([sample(1, 0), sample(2, 10)], incarnations=[None, "inc-a"])
    assert len(partial.segments) == 1
    assert partial.segments[0].incarnation_status == IncarnationStatus.UNKNOWN


def test_recorded_discontinuity_is_honored_only_when_the_contract_declares_it():
    flagged = [sample(1, 0, value=10), sample(2, 10, value=20, quality_conditions=(Quality.RESET_OR_DISCONTINUOUS,))]
    honored = run(flagged, contract_changes={"honor_recorded_discontinuity": True})
    assert reasons(honored, 1) == (BreakReason.RECORDED_DISCONTINUITY,)
    assert honored.boundaries[1].restart_asserted is False
    ignored = run(flagged)
    assert len(ignored.segments) == 1
    assert "recorded_reset_flag_not_honored_by_contract" in ignored.segments[0].limitations


@pytest.mark.parametrize("provenance,reason", [
    ({"configured_index": 1}, BreakReason.SUBJECT_CHANGE),
    ({"miner_workload_id": 8}, BreakReason.WORKLOAD_CHANGE),
    ({"raw_algorithm_name": "otherhash"}, BreakReason.ALGORITHM_CHANGE),
])
def test_subject_workload_and_algorithm_change_each_break_the_segment(provenance, reason):
    changed = {"configured_index": 0, "miner_workload_id": 7, "raw_algorithm_name": "pearlhash",
               **provenance}
    result = run([sample(1, 0), sample(2, 10, provenance=changed)])
    assert len(result.segments) == 2
    assert reasons(result, 1) == (reason,)
    assert result.boundaries[1].evidence == (f"{reason.name.split('_')[0].lower()}_identity_basis_changed",)


def test_alias_rewrite_inside_one_canonical_algorithm_does_not_break_the_segment():
    result = run([sample(1, 0, provenance={"configured_index": 0, "miner_workload_id": 7,
                                           "raw_algorithm_name": "pearlhash"}),
                  sample(2, 10, provenance={"configured_index": 0, "miner_workload_id": 7,
                                            "raw_algorithm_name": "PearlPow"})])
    assert len(result.segments) == 1
    assert result.segments[0].algorithm_id == "pearlpow"


def test_counter_unit_change_breaks_as_a_counter_semantics_change():
    result = run([sample(1, 0, unit="count"), sample(2, 10, unit="kJ")])
    assert len(result.segments) == 2
    assert reasons(result, 1) == (BreakReason.COUNTER_SEMANTICS_CHANGE,)
    assert "declared_counter_unit_changed" in result.boundaries[1].evidence


def test_counter_value_kind_change_breaks_as_a_counter_semantics_change():
    result = run([sample(1, 0, value=10), sample(2, 10, value="unavailable")])
    assert len(result.segments) == 2
    assert reasons(result, 1) == (BreakReason.COUNTER_SEMANTICS_CHANGE,)
    assert "declared_counter_value_semantics_changed" in result.boundaries[1].evidence


def test_excessive_gap_breaks_only_beyond_the_declared_maximum():
    at_limit = run([sample(1, 0), sample(2, 60.0)])
    assert len(at_limit.segments) == 1
    beyond = run([sample(1, 0), sample(2, 60.001)])
    assert len(beyond.segments) == 2
    assert reasons(beyond, 1) == (BreakReason.EXCESSIVE_GAP,)
    assert beyond.boundaries[1].elapsed_seconds == 60.001


def test_no_gap_or_counter_rule_is_invented_when_the_contract_is_silent():
    result = run([sample(1, 0, value=10), sample(2, 3600.0, value=5)],
                 contract_changes={"maximum_gap_seconds": None, "counter_semantics": None})
    assert len(result.segments) == 1
    limitations = result.segments[0].limitations
    assert "gap_break_not_configured" in limitations
    assert "counter_semantics_not_declared" in limitations


def test_recorded_out_of_order_evidence_is_an_unresolved_ordering_conflict():
    result = run([sample(1, 0, value=10),
                  sample(2, 10, value=20, quality_conditions=(Quality.OUT_OF_ORDER,))])
    assert len(result.segments) == 2
    assert reasons(result, 1) == (BreakReason.UNRESOLVED_ORDERING_CONFLICT,)
    assert result.boundaries[1].evidence == (
        "recorded_source_ordering_regression_without_accepted_proof",)
    assert result.segments[1].observation_ids == (UUID(int=2),)


def test_evidence_without_a_declared_basis_time_is_unassigned_not_reordered():
    result = run([sample(1, 0, value=10), sample(2, 10, value=20, observation_time=None),
                  sample(3, 20, value=30)])
    assert [segment.observation_ids for segment in result.segments] == [
        (UUID(int=1), UUID(int=3))]
    assert len(result.unassigned) == 1
    entry = result.unassigned[0]
    assert entry.observation_id == UUID(int=2)
    assert entry.reason == BreakReason.UNRESOLVED_ORDERING_CONFLICT
    assert entry.detail == "ordering_basis_time_unavailable"


def test_unresolved_identity_is_unassigned_and_never_guessed():
    result = run([sample(1, 0, value=10), sample(2, 10, value=20),
                  sample(3, 20, value=30, provenance={"configured_index": 99,
                                                      "miner_workload_id": 7,
                                                      "raw_algorithm_name": "pearlhash"})])
    assert [segment.observation_ids for segment in result.segments] == [
        (UUID(int=1), UUID(int=2))]
    assert result.unassigned[0].reason == BreakReason.UNRESOLVED_IDENTITY_CONFLICT
    assert result.unassigned[0].detail == "unresolved_identity_components:subject"


def test_receipt_basis_segments_record_that_receipt_time_is_not_a_source_interval():
    samples = [sample(1, 0, observation_time=None), sample(2, 10, observation_time=None)]
    result = run(samples, contract_changes={"ordering_basis": TimeBasis.GUARDIAN_RECEIPT_TIME})
    assert len(result.segments) == 1
    assert result.segments[0].ordering_basis == TimeBasis.GUARDIAN_RECEIPT_TIME
    assert "receipt_basis_is_not_a_source_event_interval" in result.segments[0].limitations


def test_multiple_applicable_conditions_are_all_retained_in_deterministic_order():
    changed = {"configured_index": 1, "miner_workload_id": 7, "raw_algorithm_name": "pearlhash"}
    result = run([sample(1, 0, value=100), sample(2, 600.0, value=5, provenance=changed)])
    assert len(result.segments) == 2
    assert reasons(result, 1) == (BreakReason.COUNTER_DECREASE_OR_RESET, BreakReason.SUBJECT_CHANGE,
                                  BreakReason.EXCESSIVE_GAP)
    assert len(result.boundaries[1].evidence) == 3


def test_new_segment_must_meet_its_own_sample_and_elapsed_minimum():
    result = run([sample(1, 0, value=10), sample(2, 10, value=20), sample(3, 20, value=30),
                  sample(4, 30, value=5)],
                 contract_changes={"minimum_segment_samples": 3})
    assert len(result.segments) == 2
    assert result.segments[0].observation_ids == (UUID(int=1), UUID(int=2), UUID(int=3))
    assert result.segments[0].evidence_sufficient_for_derivation is True
    assert result.segments[1].evidence_sufficient_for_derivation is False
    assert "segment_below_declared_derivation_minimum" in result.segments[1].limitations


def test_no_cross_segment_delta_or_rate_is_derivable_and_negative_delta_is_never_clamped():
    result = run([sample(1, 0, value=20), sample(2, 10, value=5)])
    index = segment_index(result)
    assert index[str(UUID(int=1))] != index[str(UUID(int=2))]
    with pytest.raises(CrossSegmentError, match="across a segment boundary"):
        require_shared_segment(result, UUID(int=1), UUID(int=2))
    assert set(result.segments[0].observation_ids).isdisjoint(result.segments[1].observation_ids)
    assert not hasattr(continuity_module, "delta")
    assert not hasattr(continuity_module, "rate")
    assert not hasattr(continuity_module, "slope")
    with pytest.raises(CrossSegmentError, match="not assigned"):
        require_shared_segment(result, UUID(int=1), UUID(int=99))


def test_shared_segment_lookup_returns_the_single_arithmetic_scope():
    result = run([sample(1, 0, value=10), sample(2, 10, value=20), sample(3, 20, value=30)])
    shared = require_shared_segment(result, UUID(int=1), UUID(int=3))
    assert shared == result.segments[0].segment_id
    assert set(segment_index(result).values()) == {result.segments[0].segment_id}


def test_segmentation_is_deterministic_under_shuffled_input_order():
    records = [sample(1, 0, value=10), sample(2, 10, value=20),
               sample(3, 20, value=5), sample(4, 30, value=7)]
    forward = run(records)
    backward = run(list(reversed(records)))
    assert forward == backward
    assert [segment.observation_ids for segment in forward.segments] == [
        (UUID(int=1), UUID(int=2)), (UUID(int=3), UUID(int=4))]


def test_segment_identity_changes_when_identity_relevant_inputs_change():
    first = run([sample(1, 0, value=10), sample(2, 10, value=20)])
    second = run([sample(1, 0, value=10)])
    assert first.segments[0].segment_id != second.segments[0].segment_id
    assert first.segments[0].segment_id == run(
        [sample(1, 0, value=10), sample(2, 10, value=20)]).segments[0].segment_id


def test_evidence_accounting_is_complete_bounded_and_unambiguous():
    result = run([sample(1, 0, value=10), sample(2, 10, value=20)])
    accounted = {identifier for segment in result.segments for identifier in segment.observation_ids}
    assert accounted == {UUID(int=1), UUID(int=2)}
    assert len(result.boundaries) == len(result.segments)
    with pytest.raises(ContinuityLimitError):
        run([sample(1, 0), sample(2, 10), sample(3, 20)],
            config=ContinuityConfig(maximum_observations=2))
    with pytest.raises(ContinuityIntegrityError, match="duplicate evidence identity"):
        run([sample(1, 0), sample(1, 10)])


@pytest.mark.parametrize("changes", [
    {"maximum_gap_seconds": 0.0},
    {"maximum_gap_seconds": -1.0},
    {"minimum_segment_samples": 0},
    {"minimum_segment_elapsed_seconds": -1.0},
    {"counter_semantics": "SOMETIMES"},
])
def test_poisoned_or_mutated_continuity_contracts_are_refused(changes):
    with pytest.raises(ValidationError):
        contract(**changes)
    record = sample(1, 0)
    mutated = contract().model_copy(update=changes)
    with pytest.raises(ContinuityIntegrityError):
        segment_evidence([ScopedObservation(record=record,
                                            identity=resolve_identity(record, MAPPING))],
                         mutated, CONFIG)


def test_scoped_observation_rejects_mismatched_identity_and_blank_incarnation():
    record, other = sample(1, 0), sample(2, 10)
    with pytest.raises(ValidationError, match="different observation"):
        ScopedObservation(record=record, identity=resolve_identity(other, MAPPING))
    with pytest.raises(ValidationError, match="cannot be blank"):
        ScopedObservation(record=record, identity=resolve_identity(record, MAPPING),
                          incarnation="   ")



