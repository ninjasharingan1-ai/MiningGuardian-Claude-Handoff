"""M3.2-S3-A subject, workload and algorithm identity-resolution tests.

No registry access, no network, no live source: immutable mapping snapshots only.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from mining_guardian.observability.models import Quality, RuntimeObservation, Source
from mining_guardian.state.subjects import (
    ALGORITHM_ALIAS_NORMALIZATION,
    IdentityComponentStatus,
    SubjectMapping,
    SubjectResolutionConfig,
    SubjectResolutionIntegrityError,
    SubjectResolutionLimitError,
    canonical_identity_payload,
    compose_identity_key,
    deterministic_digest,
    deterministic_uuid,
    normalize_algorithm_token,
    resolve_identities,
    resolve_identity,
)

T = datetime(2026, 1, 1, tzinfo=UTC)
CONFIG = SubjectResolutionConfig(maximum_observations=64)


def observation(**changes) -> RuntimeObservation:
    data = {
        "source": Source.NVML, "source_instance": "uuid:GPU-1", "signal": "temperature_c",
        "value": 50, "unit": "degC", "observation_time": T, "ingestion_time": T,
        "correlation_id": uuid4(), "quality": Quality.VALID,
        "provenance": {"configured_index": 0, "raw_algorithm_name": "pearlhash"},
    }
    data.update(changes)
    return RuntimeObservation(**data)


def mapping(**changes) -> SubjectMapping:
    data = {
        "mapping_id": "snapshot-1", "mapping_version": "v1",
        "subject_provenance_keys": ("configured_index",),
        "include_source_instance_in_subject_key": False,
        "subjects": {"configured_index=0": "gpu-0", "configured_index=1": "gpu-1"},
        "workload_provenance_keys": ("miner_workload_id",),
        "workloads": {"miner_workload_id=7": "workload-7"},
        "algorithm_provenance_key": "raw_algorithm_name",
        "algorithms": {"pearlhash": "pearlpow", "pearlpow": "pearlpow"},
    }
    data.update(changes)
    return SubjectMapping(**data)


@pytest.mark.parametrize("raw_name", ["pearlhash", "pearlpow", "PearlPow", "PEARLPOW", " Pearl-Hash "])
def test_declared_aliases_resolve_to_one_canonical_algorithm_and_keep_raw_token(raw_name):
    record = observation(provenance={"configured_index": 0, "raw_algorithm_name": raw_name})
    identity = resolve_identity(record, mapping())
    assert identity.algorithm.status == IdentityComponentStatus.RESOLVED
    assert identity.algorithm.resolved_id == "pearlpow"
    assert identity.algorithm.source_token == raw_name
    assert identity.algorithm.composed_key == normalize_algorithm_token(raw_name)
    assert ALGORITHM_ALIAS_NORMALIZATION in identity.algorithm.facts


def test_alias_similarity_alone_never_unifies_algorithms():
    snapshot = mapping(algorithms={"pearlhash": "pearlpow"})
    identity = resolve_identity(
        observation(provenance={"configured_index": 0, "raw_algorithm_name": "pearlpow"}), snapshot)
    assert identity.algorithm.status == IdentityComponentStatus.UNRESOLVED
    assert identity.algorithm.resolved_id is None
    assert identity.algorithm.reason == "algorithm_alias_not_certified_by_mapping_snapshot"


def test_unknown_algorithm_is_preserved_and_never_remapped():
    identity = resolve_identity(
        observation(provenance={"configured_index": 0, "raw_algorithm_name": "  MyNewAlgo  "}),
        mapping())
    assert identity.algorithm.status == IdentityComponentStatus.UNRESOLVED
    assert identity.algorithm.source_token == "  MyNewAlgo  "
    assert identity.algorithm.composed_key == "mynewalgo"
    assert identity.algorithm.resolved_id is None


def test_row_position_is_never_identity():
    snapshot = mapping()
    first = resolve_identity(
        observation(provenance={"configured_index": 0, "raw_algorithm_name": "pearlhash",
                                "payload_position": 0}), snapshot)
    second = resolve_identity(
        observation(provenance={"configured_index": 0, "raw_algorithm_name": "pearlhash",
                                "payload_position": 9}), snapshot)
    assert first.subject == second.subject
    assert first.subject.composed_key == "configured_index=0"
    assert "position" not in first.subject.composed_key


def test_missing_declared_key_leaves_identity_unresolved():
    identity = resolve_identity(observation(provenance={"raw_algorithm_name": "pearlhash"}), mapping())
    assert identity.subject.status == IdentityComponentStatus.UNRESOLVED
    assert identity.subject.reason == "subject_key_evidence_incomplete"
    assert identity.subject.composed_key is None
    assert "declared_key_absent_from_provenance:configured_index" in identity.subject.facts


def test_uncertified_subject_key_keeps_composed_key_and_identity_unknown():
    identity = resolve_identity(
        observation(provenance={"configured_index": 42, "raw_algorithm_name": "pearlhash"}),
        mapping())
    assert identity.subject.status == IdentityComponentStatus.UNRESOLVED
    assert identity.subject.composed_key == "configured_index=42"
    assert identity.subject.resolved_id is None
    assert identity.subject.reason == "subject_key_not_certified_by_mapping_snapshot"


def test_undeclared_components_stay_explicitly_undeclared():
    snapshot = mapping(workload_provenance_keys=(), workloads={},
                       algorithm_provenance_key=None, algorithms={})
    identity = resolve_identity(observation(provenance={"configured_index": 0}), snapshot)
    assert identity.workload.status == IdentityComponentStatus.NOT_DECLARED
    assert identity.algorithm.status == IdentityComponentStatus.NOT_DECLARED
    assert identity.subject.status == IdentityComponentStatus.RESOLVED
    assert "algorithm:NOT_DECLARED" in identity.scope_key


@pytest.mark.parametrize("value,reason", [
    (True, "boolean_is_not_an_identity:configured_index"),
    (False, "boolean_is_not_an_identity:configured_index"),
    (0.5, "unsupported_identity_value:configured_index"),
    (None, "unsupported_identity_value:configured_index"),
    ({"nested": 0}, "unsupported_identity_value:configured_index"),
    ([0], "unsupported_identity_value:configured_index"),
])
def test_only_string_and_integer_provenance_values_can_be_identities(value, reason):
    record = observation(provenance={"configured_index": value})
    identity = resolve_identity(record, mapping())
    assert identity.subject.status == IdentityComponentStatus.UNRESOLVED
    assert reason in identity.subject.facts


def test_identity_value_cannot_smuggle_a_key_separator():
    record = observation(provenance={"configured_index": "0|configured_index=1"})
    identity = resolve_identity(record, mapping())
    assert identity.subject.status == IdentityComponentStatus.UNRESOLVED
    assert "identity_value_contains_reserved_separator:configured_index" in identity.subject.facts


def test_identity_value_cannot_smuggle_an_equals_separator():
    record = observation(provenance={"configured_index": "0=1"})
    identity = resolve_identity(record, mapping())
    assert identity.subject.status == IdentityComponentStatus.UNRESOLVED
    assert "identity_value_contains_reserved_separator:configured_index" in identity.subject.facts


def test_composed_key_is_unambiguous_for_multiple_declared_keys():
    record = observation(provenance={"configured_index": 3, "device_namespace": "srbminer"})
    key, facts = compose_identity_key(record, ("configured_index", "device_namespace"))
    assert key == "configured_index=3|device_namespace=srbminer"
    assert facts == ()
    assert compose_identity_key(record, ("configured_index", "device_namespace", "absent"))[0] is None


def test_cross_source_identity_is_unified_only_by_declaration():
    snapshot = mapping(subject_provenance_keys=(), include_source_instance_in_subject_key=True,
                       subjects={"source_instance=uuid:GPU-1": "gpu-0",
                                 "source_instance=miner-0": "gpu-0"})
    nvml = resolve_identity(observation(), snapshot)
    miner = resolve_identity(observation(source=Source.SRBMINER_HTTP, source_instance="miner-0",
                                         signal="hashrate_hs", unit="H/s"), snapshot)
    assert nvml.subject.resolved_id == "gpu-0"
    assert miner.subject.resolved_id == "gpu-0"
    assert nvml.subject.composed_key != miner.subject.composed_key
    unknown = resolve_identity(observation(source_instance="miner-9"), snapshot)
    assert unknown.subject.status == IdentityComponentStatus.UNRESOLVED


def test_source_instance_basis_requires_an_instance_identity():
    snapshot = mapping(subject_provenance_keys=(), include_source_instance_in_subject_key=True,
                       subjects={"source_instance=uuid:GPU-1": "gpu-0"})
    identity = resolve_identity(observation(source_instance=None), snapshot)
    assert identity.subject.status == IdentityComponentStatus.UNRESOLVED
    assert "source_instance_unavailable_for_declared_subject_key" in identity.subject.facts


def test_mapping_snapshot_is_immutable_and_insulated_from_caller_mutation():
    subjects = {"configured_index=0": "gpu-0"}
    snapshot = mapping(subjects=subjects)
    first = resolve_identity(observation(), snapshot)
    subjects["configured_index=0"] = "attacker-controlled"
    subjects["configured_index=7"] = "injected"
    second = resolve_identity(observation(), snapshot)
    assert first.subject == second.subject
    assert second.subject.resolved_id == "gpu-0"
    with pytest.raises(TypeError):
        snapshot.subjects["configured_index=0"] = "mutated"
    injected = resolve_identity(observation(provenance={"configured_index": 7}), snapshot)
    assert injected.subject.status == IdentityComponentStatus.UNRESOLVED


@pytest.mark.parametrize("changes", [
    {"subject_provenance_keys": (), "include_source_instance_in_subject_key": False,
     "subjects": {"configured_index=0": "gpu-0"}},
    {"subject_provenance_keys": ("configured_index",), "subjects": {}},
    {"subject_provenance_keys": ("configured_index", "configured_index")},
    {"workload_provenance_keys": ("miner_workload_id",), "workloads": {}},
    {"workload_provenance_keys": (), "workloads": {"miner_workload_id=7": "w"}},
    {"algorithm_provenance_key": None},
    {"algorithms": {"PearlHash": "pearlpow"}},
    {"algorithms": {"pearlhash": ""}},
    {"subjects": {"configured_index=0": ""}},
])
def test_incoherent_or_unnormalized_mapping_declarations_are_rejected(changes):
    with pytest.raises(ValidationError):
        mapping(**changes)


@pytest.mark.parametrize("key", ["raw algorithm!", "raw-algorithm", "", "a" * 65])
def test_algorithm_provenance_key_must_be_a_safe_identifier(key):
    with pytest.raises(ValidationError):
        mapping(algorithm_provenance_key=key)


def test_resolution_is_canonically_ordered_and_bounded():
    records = [observation(observation_id=UUID(int=index), provenance={"configured_index": index % 2})
               for index in range(1, 6)]
    forward = resolve_identities(records, mapping(), CONFIG)
    backward = resolve_identities(list(reversed(records)), mapping(), CONFIG)
    assert forward == backward
    assert [identity.observation_id for identity in forward] == sorted(
        (UUID(int=index) for index in range(1, 6)), key=str)
    with pytest.raises(SubjectResolutionLimitError):
        resolve_identities(records, mapping(), SubjectResolutionConfig(maximum_observations=4))


def test_duplicate_evidence_identity_is_refused():
    records = [observation(observation_id=UUID(int=1)), observation(observation_id=UUID(int=1))]
    with pytest.raises(SubjectResolutionIntegrityError):
        resolve_identities(records, mapping(), CONFIG)


def test_structurally_forged_observation_is_refused():
    forged = observation().model_copy(update={"quality": "NOT_A_QUALITY"})
    with pytest.raises(SubjectResolutionIntegrityError):
        resolve_identity(forged, mapping())
    with pytest.raises(SubjectResolutionIntegrityError):
        resolve_identity({"not": "an observation"}, mapping())


def test_deterministic_identity_helpers_are_stable_and_content_sensitive():
    assert canonical_identity_payload(["a", "b|c"]) == '["a","b|c"]'
    assert deterministic_uuid("conflict", ["a", "b"]) == deterministic_uuid("conflict", ["a", "b"])
    assert deterministic_uuid("conflict", ["a", "b"]) != deterministic_uuid("conflict", ["a", "c"])
    assert deterministic_uuid("conflict", ["a"]) != deterministic_uuid("segment", ["a"])
    assert deterministic_digest("segment", ["a"]) == deterministic_digest("segment", ["a"])
    assert deterministic_digest("segment", ["a"]) != deterministic_digest("segment", ["a", "b"])
    assert deterministic_uuid("conflict", ["a"]).version == 5
    assert len(deterministic_digest("segment", ["a"])) == 64
    with pytest.raises(ValueError, match="namespace"):
        deterministic_uuid("", ["a"])
    with pytest.raises(ValueError, match="namespace"):
        deterministic_digest("", ["a"])


def test_resolution_preserves_declared_workload_and_snapshot_identity():
    record = observation(provenance={"configured_index": 0, "miner_workload_id": 7,
                                     "raw_algorithm_name": "pearlhash"})
    identity = resolve_identity(record, mapping())
    assert identity.workload.status == IdentityComponentStatus.RESOLVED
    assert identity.workload.resolved_id == "workload-7"
    assert identity.workload.composed_key == "miner_workload_id=7"
    assert identity.mapping_id == "snapshot-1"
    assert identity.mapping_version == "v1"

