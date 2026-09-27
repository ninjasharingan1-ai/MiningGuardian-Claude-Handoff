"""M3.2-S3-D conflict-detection tests: comparability, kinds, no hidden winner."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from mining_guardian.observability.models import Quality, RuntimeObservation, Source
from mining_guardian.state.conflicts import (
    ACQUISITION_LIMITATION,
    NO_WINNER_LIMITATION,
    ComparableEvidence,
    ComparisonContract,
    ComparisonRequest,
    ConflictDetectionConfig,
    ConflictDetectionIntegrityError,
    ConflictDetectionLimitError,
    ConflictDetectionResult,
    NotComparedEvidence,
    detect_conflicts,
)
from mining_guardian.state.contracts import (
    ConflictKind,
    ConflictResolutionStatus,
    TimeBasis,
)
from mining_guardian.state.subjects import SubjectMapping, resolve_identity

T = datetime(2026, 1, 1, tzinfo=UTC)
CONFIG = ConflictDetectionConfig(maximum_candidates=16)

MAPPING = SubjectMapping(
    mapping_id="snapshot-1", mapping_version="v1",
    subject_provenance_keys=("configured_index",), include_source_instance_in_subject_key=False,
    subjects={"configured_index=0": "gpu-0", "configured_index=1": "gpu-1"},
    workload_provenance_keys=("miner_workload_id",),
    workloads={"miner_workload_id=7": "workload-7", "miner_workload_id=8": "workload-8"},
    algorithm_provenance_key="raw_algorithm_name",
    algorithms={"pearlhash": "pearlpow", "pearlpow": "pearlpow", "otherhash": "otheralgo"},
)


def candidate(index, *, source=Source.NVML, instance="uuid:GPU-1", signal="hashrate_hs",
              unit="H/s", value=1.0, offset=0.0, correlation_id=None, index_provenance=0,
              algorithm="pearlhash", workload=7,
              effective_basis=TimeBasis.SOURCE_OBSERVATION_TIME):
    record = RuntimeObservation(
        source=source, source_instance=instance, signal=signal, value=value, unit=unit,
        observation_time=T + timedelta(seconds=offset),
        ingestion_time=T + timedelta(seconds=offset),
        correlation_id=correlation_id or uuid4(), quality=Quality.VALID,
        observation_id=UUID(int=index),
        provenance={"configured_index": index_provenance, "miner_workload_id": workload,
                    "raw_algorithm_name": algorithm})
    return ComparableEvidence(
        observation_id=record.observation_id, source=record.source,
        source_instance=record.source_instance, signal=record.signal, unit=record.unit,
        value=record.value, effective_basis=effective_basis, effective_time=record.ingestion_time,
        correlation_id=record.correlation_id, identity=resolve_identity(record, MAPPING))


def contract(**changes):
    data = {"contract_id": "hashrate", "contract_version": "v1",
            "comparison_basis": "same_subject_quantity_unit_effective_interval",
            "maximum_alignment_seconds": 1.0,
            "quantities": [{"quantity_id": "miner_reported_hashrate", "signals": ["hashrate_hs"]}]}
    data.update(changes)
    return ComparisonContract(**data)


def request(**changes):
    data = {"affected_field_key": "hashrate_hs", "quantity_id": "miner_reported_hashrate",
            "expected_identity": {"subject_id": "gpu-0", "algorithm_id": "pearlpow"}}
    data.update(changes)
    return ComparisonRequest(**data)


def run(candidates, *, contract_changes=None, request_changes=None, config=CONFIG):
    return detect_conflicts(candidates, contract(**contract_changes or {}),
                            request(**request_changes or {}), config)


def test_cross_source_agreement_is_recorded_without_ranking_sources():
    result = run([candidate(1), candidate(2, source=Source.SRBMINER_HTTP, instance="miner-0")])
    assert result.conflicts == ()
    assert len(result.agreements) == 1
    agreement = result.agreements[0]
    assert agreement.participant_evidence_ids == (UUID(int=1), UUID(int=2))
    assert agreement.source_streams == ("NVML:uuid:GPU-1", "SRBMINER_HTTP:miner-0")
    assert agreement.agreed_value == 1.0
    assert agreement.unit == "H/s"
    assert agreement.effective_time_spread_seconds == 0.0


def test_comparable_disagreement_is_unresolved_with_every_participant_and_no_winner():
    result = run([candidate(1, value=1.0), candidate(2, value=2.0,
                                                   source=Source.SRBMINER_HTTP, instance="miner-0")])
    assert len(result.conflicts) == 1
    c = result.conflicts[0]
    assert c.kind == ConflictKind.VALUE_DISAGREEMENT
    assert c.resolution_status == ConflictResolutionStatus.UNRESOLVED
    assert c.selected_evidence_ids == ()
    assert c.rejected_evidence_ids == ()
    assert c.resolution_rule_id is None
    assert c.resolution_rule_version is None
    assert c.participant_evidence_ids == (UUID(int=1), UUID(int=2))
    assert c.quantified_disagreement == 1.0
    assert c.disagreement_unit == "H/s"
    assert c.affected_field_key == "hashrate_hs"
    assert c.comparison_basis == "same_subject_quantity_unit_effective_interval"
    assert c.reason == "comparable_values_disagree_without_a_resolution_policy"


def test_majority_agreement_does_not_hide_the_dissenting_participant():
    result = run([candidate(1, value=1.0), candidate(2, value=1.0, source=Source.SRBMINER_HTTP,
                                                   instance="miner-0"),
                  candidate(3, value=9.0, source=Source.POOL_DATA_FROM_MINER, instance="pool-0")])
    assert len(result.conflicts) == 1
    assert result.conflicts[0].kind == ConflictKind.VALUE_DISAGREEMENT
    assert result.conflicts[0].quantified_disagreement == 8.0


def test_identity_mismatch_is_recorded_without_unifying_sources():
    result = run([candidate(1, index_provenance=0),
                  candidate(2, index_provenance=1, source=Source.NVML)])
    assert len(result.conflicts) == 1
    assert result.conflicts[0].kind == ConflictKind.IDENTITY_MISMATCH


def test_expected_identity_mismatch_is_recorded():
    result = run([candidate(1, index_provenance=0),
                  candidate(2, index_provenance=0, source=Source.NVML)],
                 request_changes={"expected_identity": {"subject_id": "gpu-1"}})
    assert len(result.conflicts) == 1
    assert result.conflicts[0].kind == ConflictKind.IDENTITY_MISMATCH


def test_unit_mismatch_is_comparable_semantics_not_value_disagreement():
    result = run([candidate(1, unit="H/s"),
                  candidate(2, unit="MH/s", source=Source.NVML)])
    assert len(result.conflicts) == 1
    assert result.conflicts[0].kind == ConflictKind.UNIT_OR_SEMANTIC_MISMATCH


def test_value_kind_mismatch_is_comparable_semantics_not_value_disagreement():
    result = run([candidate(1, value=8.0),
                  candidate(2, value="fast", source=Source.NVML)])
    assert len(result.conflicts) == 1
    assert result.conflicts[0].kind == ConflictKind.UNIT_OR_SEMANTIC_MISMATCH

def test_amount_mismatch_is_seen_as_temporal_misalignment_for_near_but_different_times():
    shared = uuid4()
    result = run([candidate(1, value=5.0, correlation_id=shared),
                   candidate(2, offset=5.0, value=5.0,
                             source=Source.SRBMINER_HTTP, instance="miner-0", correlation_id=shared)])
    assert len(result.conflicts) == 1
    assert result.conflicts[0].kind == ConflictKind.TEMPORAL_MISALIGNMENT


def test_temporal_misalignment_and_value_disagreement_are_distinct():
    result = run([candidate(1, value=5.0),
                  candidate(2, offset=0.5, value=7.0,
                            source=Source.SRBMINER_HTTP, instance="miner-0")])
    assert len(result.conflicts) == 1
    assert result.conflicts[0].kind == ConflictKind.VALUE_DISAGREEMENT


def test_shared_correlation_identity_does_not_collapse_temporal_reality():
    shared = uuid4()
    result = run([candidate(1, value=1.0, correlation_id=shared),
                   candidate(2, offset=5.0, value=1.0, source=Source.SRBMINER_HTTP, instance="miner-0",
                             correlation_id=shared)])
    assert len(result.conflicts) == 1
    assert result.conflicts[0].kind == ConflictKind.TEMPORAL_MISALIGNMENT
    assert ACQUISITION_LIMITATION in result.limitations



def test_single_candidate_is_not_compared_as_if_deficient():
    result = run([candidate(1)])
    assert result.agreements == ()
    assert result.conflicts == ()
    assert result.not_compared == (NotComparedEvidence(
        observation_id=UUID(int=1), reason="comparison_requires_at_least_two_source_streams",
        detail="cross-source comparison requires evidence from at least two source streams"),)


def test_bounded_and_duplicate_candidates_are_refused():
    with pytest.raises(ConflictDetectionLimitError):
        run([candidate(i) for i in range(1, 20)], config=ConflictDetectionConfig(maximum_candidates=15))
    with pytest.raises(ConflictDetectionIntegrityError, match="duplicate candidate identity"):
        run([candidate(1), candidate(1)])


def test_multi_way_agreement_keeps_all_three_streams_distinct():
    result = run([candidate(1, value=1.0),
                   candidate(2, value=1.0, source=Source.SRBMINER_HTTP, instance="miner-0"),
                   candidate(3, value=1.0, source=Source.POOL_DATA_FROM_MINER, instance="pool-0")])
    assert len(result.agreements) == 1
    ag = result.agreements[0]
    assert ag.participant_evidence_ids == (UUID(int=1), UUID(int=2), UUID(int=3))
    assert len(ag.source_streams) == 3
    assert {"NVML:uuid:GPU-1", "SRBMINER_HTTP:miner-0", "POOL_DATA_FROM_MINER:pool-0"} == set(ag.source_streams)
    assert ag.agreed_value == 1.0
    assert ag.unit == "H/s"
    assert ag.effective_basis == TimeBasis.SOURCE_OBSERVATION_TIME
