"""Contract tests for the S4A R1 foundations and R2-A authority binding."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from inspect import signature
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

import mining_guardian.state.methods as methods
from mining_guardian.observability.models import Quality, RuntimeObservation, Source
from mining_guardian.state.admission import AdmissionConfig, assess_admission
from mining_guardian.state.conflicts import (
    ComparableEvidence,
    ComparisonContract,
    ComparisonRequest,
    ConflictDetectionConfig,
    NotComparedEvidence,
    detect_conflicts,
)
from mining_guardian.state.continuity import (
    BreakReason,
    ContinuityConfig,
    ContinuityContract,
    ScopedObservation,
    UnassignedEvidence,
    segment_evidence,
)
from mining_guardian.state.contracts import (
    FieldEvidenceContract,
    FieldRequest,
    SignalRequirement,
    TimeBasis,
)
from mining_guardian.state.evidence_query import (
    AssociationMode,
    EvidenceQueryContinuation,
    EvidenceQueryRequest,
    EvidenceQueryResult,
    QueryCompleteness,
    QueryIntegrity,
)
from mining_guardian.state.methods import (
    AuthoritativeAnalyticalSet,
    AuthoritativeMethodInput,
    ConflictBinding,
    ContinuityViolationError,
    DeterministicArithmeticError,
    DuplicateObservationIdentityError,
    ExactNumber,
    FieldContractBindingError,
    InvalidMethodConfigurationError,
    MalformedAuthoritativeInputError,
    MalformedS3ArtifactError,
    MethodConfiguration,
    MethodConfigurationSemanticPayload,
    MethodConstructionError,
    MethodError,
    MethodEvidenceUse,
    MethodName,
    MethodNoResult,
    MethodNoResultReason,
    MethodOperationError,
    MethodResourceLimitError,
    MethodUnitSemantics,
    MethodValueResult,
    MethodVersion,
    UnknownMethodError,
    UnsupportedMethodVersionError,
    UnsupportedValueKindError,
    build_method_configuration,
    method_configuration_digest,
    supported_method_versions,
)
from mining_guardian.state.subjects import (
    SubjectMapping,
    SubjectResolutionConfig,
    resolve_identities,
)


def field_contract(
    *,
    contract_id: str = "gpu-temperature",
    contract_version: str = "v1",
    **changes: object,
) -> FieldEvidenceContract:
    signal = SignalRequirement(
        source="NVML",
        signal="temperature_c",
        source_semantics="m3.1.nvml.temperature",
        unit="degC",
    )
    data: dict[str, object] = {
        "contract_id": contract_id,
        "contract_version": contract_version,
        "field_key": "temperature_c",
        "estimand": "GPU temperature at reference time",
        "subject_scope": "gpu_uuid",
        "required_signals": (signal,),
        "optional_signals": (),
        "identity_requirements": ("gpu_uuid",),
        "allowed_units": ("degC",),
        "allowed_conversions": (),
        "admissible_quality": (Quality.VALID,),
        "temporal_basis": TimeBasis.SOURCE_OBSERVATION_TIME,
        "window_seconds": 30,
        "minimum_samples": 1,
        "minimum_span_seconds": 0,
        "minimum_coverage_fraction": None,
        "maximum_gap_seconds": None,
        "continuity_rule": "not_applicable",
        "conflict_rule": "unresolved_unknown",
        "permitted_degradation_rules": (),
        "confidence_rubric_id": "temperature-support",
        "confidence_rubric_version": "v1",
        "output_type": "number",
        "output_unit": "degC",
        "maximum_records": 100,
        "maximum_decoded_bytes": 10_000,
        "maximum_subjects": 1,
        "predecessor_lookback_seconds": 0,
    }
    data.update(changes)
    return FieldEvidenceContract(**data)


def configuration(
    method_name: MethodName | str = MethodName.ARITHMETIC_MEAN,
    *,
    contract: FieldEvidenceContract | None = None,
) -> MethodConfiguration:
    return build_method_configuration(
        method_name=method_name,
        method_version=MethodVersion.V1,
        field_contract=contract or field_contract(),
    )


def serialized(configuration_value: MethodConfiguration) -> dict[str, object]:
    return configuration_value.model_dump(mode="json")


def use(identifier: int, role: str = "USED") -> MethodEvidenceUse:
    return MethodEvidenceUse(
        observation_id=UUID(int=identifier),
        role=role,
        reason="supports_method" if role == "USED" else "excluded_by_method",
    )


def test_exact_nine_method_names_and_explicit_v1_support():
    assert [item.value for item in MethodName] == [
        "latest_eligible_value",
        "arithmetic_mean",
        "median",
        "min",
        "max",
        "within_segment_delta",
        "source_time_counter_rate",
        "historical_endpoint_slope",
        "missing_fraction",
    ]
    assert tuple(MethodVersion) == (MethodVersion.V1,)
    versions = supported_method_versions()
    assert isinstance(versions, MappingProxyType)
    assert set(versions) == set(MethodName)
    assert all(value == frozenset({MethodVersion.V1}) for value in versions.values())
    with pytest.raises(TypeError):
        versions[MethodName.MEDIAN] = frozenset()  # type: ignore[index]


@pytest.mark.parametrize("alias", ["latest", "mean", "average", "rate", "slope"])
def test_method_aliases_are_refused(alias: str):
    with pytest.raises(UnknownMethodError):
        configuration(alias)


def test_unsupported_version_is_refused_without_fallback():
    with pytest.raises(UnsupportedMethodVersionError):
        build_method_configuration(
            method_name=MethodName.MEDIAN,
            method_version="latest",
            field_contract=field_contract(),
        )


def test_configuration_and_payload_are_immutable_and_parameters_are_empty():
    config = configuration()
    assert config.semantic_payload.semantic_parameters == ()
    with pytest.raises(ValidationError):
        config.semantic_payload.method_name = MethodName.MEDIAN
    with pytest.raises(ValidationError):
        config.configuration_sha256 = "0" * 64
    with pytest.raises(ValidationError):
        config.model_copy(update={"configuration_sha256": "0" * 64})


def test_invariant_models_disable_nonvalidating_model_construct():
    for model_type in (
        ExactNumber,
        MethodConfigurationSemanticPayload,
        MethodConfiguration,
        MethodUnitSemantics,
        MethodEvidenceUse,
        MethodValueResult,
        MethodNoResult,
    ):
        with pytest.raises(TypeError, match=r"model_construct.*disabled"):
            model_type.model_construct()


def test_invariant_models_disable_deprecated_nonvalidating_copy():
    config = configuration()
    unit = MethodUnitSemantics(kind="FIELD_VALUE", value_unit="degC")
    evidence = use(1)
    value_result = MethodValueResult(
        configuration=config,
        value=ExactNumber.from_value(7),
        unit_semantics=unit,
        evidence_use=(evidence,),
    )
    no_result = MethodNoResult(
        configuration=config,
        reason=MethodNoResultReason.INSUFFICIENT_CARDINALITY,
    )
    cases = (
        (ExactNumber.from_ratio(1, 2), {"update": {"denominator": 0}}),
        (config.semantic_payload, {"update": {"semantic_parameters": ("not-authorized",)}}),
        (config, {"update": {"configuration_sha256": "0" * 64}}),
        (unit, {"update": {"kind": "DIMENSIONLESS"}}),
        (evidence, {"update": {"role": "IGNORED"}}),
        (value_result, {"exclude": {"value"}}),
        (no_result, {"update": {"outcome_kind": "VALUE"}}),
    )

    for model, kwargs in cases:
        with pytest.raises(TypeError, match=r"copy\(\) is disabled; use model_copy\(\)"):
            model.copy(**kwargs)


def test_standard_copy_protocols_remain_safe_and_nonmutating():
    config = configuration()
    result = MethodValueResult(
        configuration=config,
        value=ExactNumber.from_value(7),
        unit_semantics=MethodUnitSemantics(kind="FIELD_VALUE", value_unit="degC"),
        evidence_use=(use(1),),
    )
    original_state = result.model_dump(mode="python", round_trip=True)

    shallow = copy.copy(result)
    deep = copy.deepcopy(result)

    assert shallow == result
    assert shallow is not result
    assert shallow.configuration is result.configuration
    assert deep == result
    assert deep is not result
    assert deep.configuration is not result.configuration
    assert result.model_dump(mode="python", round_trip=True) == original_state


def test_validated_model_copy_preserves_nested_configuration_integrity():
    config = configuration()
    copied = config.model_copy(deep=True)
    assert copied == config
    assert copied.configuration_sha256 == config.configuration_sha256
    assert copied.semantic_payload is not config.semantic_payload


def test_canonical_json_is_exact_compact_sorted_utf8_with_empty_parameter_array():
    payload = configuration().semantic_payload
    canonical = payload.canonical_json_bytes()
    assert canonical == (
        b'{"field_contract_id":"gpu-temperature",'
        b'"field_contract_version":"v1",'
        b'"method_name":"arithmetic_mean",'
        b'"method_version":"v1",'
        b'"schema_version":"m3.2.method-configuration.v1",'
        b'"semantic_parameters":[]}'
    )
    assert json.loads(canonical.decode("utf-8"))["semantic_parameters"] == []


def test_repeated_construction_has_identical_payload_bytes_and_digest():
    first = configuration()
    second = configuration()
    assert first.semantic_payload == second.semantic_payload
    assert first.semantic_payload.canonical_json_bytes() == second.semantic_payload.canonical_json_bytes()
    assert first.configuration_sha256 == second.configuration_sha256
    assert first == second


def test_digest_hashes_payload_only_and_never_the_envelope():
    config = configuration()
    canonical = config.semantic_payload.canonical_json_bytes()
    assert b"configuration_sha256" not in canonical
    assert method_configuration_digest(config.semantic_payload) == hashlib.sha256(canonical).hexdigest()
    envelope_bytes = json.dumps(
        serialized(config), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert hashlib.sha256(envelope_bytes).hexdigest() != config.configuration_sha256
    with pytest.raises(InvalidMethodConfigurationError):
        method_configuration_digest(config)  # type: ignore[arg-type]


def test_deserialization_rejects_nonempty_parameters_and_unknown_fields():
    config_data = serialized(configuration())
    payload = dict(config_data["semantic_payload"])
    payload["semantic_parameters"] = [{"name": "not-authorized"}]
    with pytest.raises(InvalidMethodConfigurationError):
        MethodConfiguration.from_serialized({**config_data, "semantic_payload": payload})

    with pytest.raises(InvalidMethodConfigurationError):
        MethodConfiguration.from_serialized({**config_data, "unknown": "field"})

    payload = dict(config_data["semantic_payload"])
    payload["parameter_alias"] = []
    with pytest.raises(InvalidMethodConfigurationError):
        MethodConfiguration.from_serialized({**config_data, "semantic_payload": payload})


def test_semantic_payload_copy_cannot_forge_nonempty_parameters():
    payload = configuration().semantic_payload
    with pytest.raises(ValidationError, match="explicit empty collection"):
        payload.model_copy(update={"semantic_parameters": ("not-authorized",)})


def test_forged_nonempty_payload_cannot_canonicalize_or_receive_a_digest():
    payload = configuration().semantic_payload.model_copy()
    object.__setattr__(payload, "semantic_parameters", ("not-authorized",))

    with pytest.raises(ValidationError, match="explicit empty collection"):
        payload.canonical_json_bytes()
    with pytest.raises(ValidationError, match="explicit empty collection"):
        method_configuration_digest(payload)


def test_canonicalization_does_not_coerce_forged_payload_state_into_validity():
    payload = configuration().semantic_payload.model_copy()
    object.__setattr__(payload, "semantic_parameters", [])

    with pytest.raises(ValueError, match="already be in validated canonical state"):
        payload.canonical_json_bytes()
    with pytest.raises(ValueError, match="already be in validated canonical state"):
        method_configuration_digest(payload)


def test_configuration_revalidates_an_already_created_nested_payload_instance():
    config = configuration()
    forged_payload = config.semantic_payload.model_copy()
    object.__setattr__(forged_payload, "semantic_parameters", ("not-authorized",))

    with pytest.raises(ValidationError, match="explicit empty collection"):
        MethodConfiguration(
            semantic_payload=forged_payload,
            configuration_sha256=config.configuration_sha256,
        )


def test_deserialization_rejects_tampered_missing_malformed_or_uppercase_digest():
    config_data = serialized(configuration())
    for replacement in ("0" * 64, "bad", configuration().configuration_sha256.upper()):
        with pytest.raises(InvalidMethodConfigurationError):
            MethodConfiguration.from_serialized(
                {**config_data, "configuration_sha256": replacement}
            )
    without_digest = {key: value for key, value in config_data.items() if key != "configuration_sha256"}
    with pytest.raises(InvalidMethodConfigurationError):
        MethodConfiguration.from_serialized(without_digest)


def test_deserialization_rejects_unsupported_schema_method_version_and_duplicate_json_key():
    config_data = serialized(configuration())
    for field, replacement in (
        ("schema_version", "m3.2.method-configuration.v2"),
        ("method_name", "mean"),
        ("method_version", "v2"),
    ):
        payload = dict(config_data["semantic_payload"])
        payload[field] = replacement
        with pytest.raises(InvalidMethodConfigurationError):
            MethodConfiguration.from_serialized({**config_data, "semantic_payload": payload})

    duplicate = (
        '{"semantic_payload":{},"semantic_payload":{},'
        '"configuration_sha256":"' + "0" * 64 + '"}'
    )
    with pytest.raises(InvalidMethodConfigurationError):
        MethodConfiguration.from_serialized(duplicate)


def test_deserialization_rejects_nested_duplicate_semantic_payload_key():
    config = configuration()
    payload_json = config.semantic_payload.canonical_json_bytes().decode("utf-8")
    duplicate_payload_json = payload_json.replace(
        '"method_name":"arithmetic_mean"',
        '"method_name":"arithmetic_mean","method_name":"median"',
    )
    serialized_json = (
        '{"configuration_sha256":"'
        + config.configuration_sha256
        + '","semantic_payload":'
        + duplicate_payload_json
        + "}"
    )

    with pytest.raises(InvalidMethodConfigurationError):
        MethodConfiguration.from_serialized(serialized_json)


@pytest.mark.parametrize(
    "model_type",
    (MethodConfigurationSemanticPayload, MethodConfiguration),
)
@pytest.mark.parametrize("loader_name", ("model_validate_json", "parse_raw"))
def test_alternate_raw_configuration_loaders_are_disabled(model_type: type, loader_name: str):
    config = configuration()
    serialized_json = json.dumps(serialized(config), separators=(",", ":"), sort_keys=True)
    loader = getattr(model_type, loader_name)

    with pytest.raises(TypeError, match=r"use MethodConfiguration\.from_serialized\(\)"):
        loader(serialized_json)


@pytest.mark.parametrize(
    "model_type",
    (MethodConfigurationSemanticPayload, MethodConfiguration),
)
def test_alternate_raw_configuration_file_loader_is_disabled(model_type: type):
    config = configuration()
    serialized_json = json.dumps(serialized(config), separators=(",", ":"), sort_keys=True)

    with TemporaryDirectory(prefix="miningguardian-s4a-r1-") as temporary_directory:
        serialized_path = Path(temporary_directory) / "configuration.json"
        serialized_path.write_text(serialized_json, encoding="utf-8")
        with pytest.raises(TypeError, match=r"use MethodConfiguration\.from_serialized\(\)"):
            model_type.parse_file(serialized_path)


def test_type_adapter_rejects_direct_raw_configuration_models():
    config = configuration()
    cases = (
        (MethodConfiguration, config.model_dump_json()),
        (MethodConfigurationSemanticPayload, config.semantic_payload.model_dump_json()),
    )

    for model_type, serialized_json in cases:
        with pytest.raises(
            ValidationError,
            match=r"use MethodConfiguration\.from_serialized\(\)",
        ):
            TypeAdapter(model_type).validate_json(serialized_json)


def test_type_adapter_rejects_nested_and_container_raw_configuration_models():
    config = configuration()
    config_json = config.model_dump_json()
    payload_json = config.semantic_payload.model_dump_json()
    result = MethodValueResult(
        configuration=config,
        value=ExactNumber.from_value(7),
        unit_semantics=MethodUnitSemantics(kind="FIELD_VALUE", value_unit="degC"),
        evidence_use=(use(1),),
    )
    cases = (
        (TypeAdapter(list[MethodConfiguration]), f"[{config_json}]"),
        (TypeAdapter(tuple[MethodConfiguration, ...]), f"[{config_json}]"),
        (TypeAdapter(dict[str, MethodConfiguration]), f'{{"configuration":{config_json}}}'),
        (TypeAdapter(list[MethodConfigurationSemanticPayload]), f"[{payload_json}]"),
        (TypeAdapter(MethodValueResult), result.model_dump_json()),
    )

    for adapter, serialized_json in cases:
        with pytest.raises(
            ValidationError,
            match=r"use MethodConfiguration\.from_serialized\(\)",
        ):
            adapter.validate_json(serialized_json)


def test_type_adapter_python_mode_and_nested_python_construction_remain_supported():
    config = configuration()
    config_data = config.model_dump(mode="python", round_trip=True)
    payload_data = config.semantic_payload.model_dump(mode="python", round_trip=True)

    restored_config = TypeAdapter(MethodConfiguration).validate_python(config_data)
    restored_payload = TypeAdapter(MethodConfigurationSemanticPayload).validate_python(
        payload_data
    )
    from_instance = MethodValueResult(
        configuration=restored_config,
        value=ExactNumber.from_value(7),
        unit_semantics=MethodUnitSemantics(kind="FIELD_VALUE", value_unit="degC"),
        evidence_use=(use(1),),
    )
    from_mapping = MethodValueResult.model_validate(
        from_instance.model_dump(mode="python", round_trip=True)
    )

    assert restored_config == config
    assert restored_payload == config.semantic_payload
    assert from_instance.configuration == config
    assert from_mapping == from_instance


def test_configuration_output_serialization_remains_available_and_deterministic():
    config = configuration()

    first_dump = config.model_dump(mode="json")
    second_dump = config.model_dump(mode="json")
    first_json = config.model_dump_json()
    second_json = config.model_dump_json()

    assert first_dump == second_dump
    assert first_json == second_json
    assert json.loads(first_json) == first_dump


def test_deserialization_rejects_missing_semantic_payload_and_payload_fields():
    config_data = serialized(configuration())
    with pytest.raises(InvalidMethodConfigurationError):
        MethodConfiguration.from_serialized(
            {"configuration_sha256": config_data["configuration_sha256"]}
        )

    payload = dict(config_data["semantic_payload"])
    del payload["semantic_parameters"]
    with pytest.raises(InvalidMethodConfigurationError):
        MethodConfiguration.from_serialized({**config_data, "semantic_payload": payload})


@pytest.mark.parametrize("field", ["field_contract_id", "field_contract_version"])
@pytest.mark.parametrize("replacement", ["", None, ["not", "a", "name"]])
def test_deserialization_rejects_empty_or_malformed_contract_identity(
    field: str,
    replacement: object,
):
    config_data = serialized(configuration())
    payload = dict(config_data["semantic_payload"])
    payload[field] = replacement
    with pytest.raises(InvalidMethodConfigurationError):
        MethodConfiguration.from_serialized({**config_data, "semantic_payload": payload})


def test_valid_json_deserialization_recomputes_and_restores_configuration():
    config = configuration()
    restored = MethodConfiguration.from_serialized(
        json.dumps(serialized(config), separators=(",", ":"), sort_keys=True)
    )
    assert restored == config
    assert restored.configuration_sha256 == config.configuration_sha256


def test_semantic_identity_dimensions_change_digest():
    base = configuration(MethodName.ARITHMETIC_MEAN)
    other_method = configuration(MethodName.MEDIAN)
    other_contract_id = configuration(contract=field_contract(contract_id="gpu-temperature-2"))
    other_contract_version = configuration(contract=field_contract(contract_version="v2"))
    digests = {
        base.configuration_sha256,
        other_method.configuration_sha256,
        other_contract_id.configuration_sha256,
        other_contract_version.configuration_sha256,
    }
    assert len(digests) == 4
    assert "semantic_content_id" not in MethodConfiguration.model_fields
    assert "semantic_content_id" not in MethodConfigurationSemanticPayload.model_fields


@pytest.mark.parametrize(
    ("method_name", "contract_id", "contract_version", "expected_digest"),
    [
        (
            MethodName.ARITHMETIC_MEAN,
            "gpu-temperature",
            "v1",
            "b2093b441bd90a2e905de0721685a06d6c25891643d621925b9976ae1433c70c",
        ),
        (
            MethodName.MEDIAN,
            "gpu-temperature-2",
            "v2",
            "3a5b88781f5923342e7d81d48abb1f869ad13277df1f3571e3cd591e6e6b3660",
        ),
        (
            MethodName.MAX,
            "温度-датчик-🌡",
            "版本-二",
            "718ffe0a95425bf2b9ebe00aa94053367be032cd0c55ed060d82c0da0e34bda6",
        ),
    ],
)
def test_independent_canonical_digest_vectors(
    method_name: MethodName,
    contract_id: str,
    contract_version: str,
    expected_digest: str,
):
    config = configuration(
        method_name,
        contract=field_contract(
            contract_id=contract_id,
            contract_version=contract_version,
        ),
    )
    assert config.configuration_sha256 == expected_digest


def test_build_configuration_has_no_parameter_or_digest_input():
    assert tuple(signature(build_method_configuration).parameters) == (
        "method_name",
        "method_version",
        "field_contract",
    )


def test_exact_number_preserves_large_integers_and_binary_float_ratio():
    above_float_identity = ExactNumber.from_value(2**53 + 1)
    huge = ExactNumber.from_value(10**400)
    binary = ExactNumber.from_value(0.1)
    assert (above_float_identity.numerator, above_float_identity.denominator) == (2**53 + 1, 1)
    assert (huge.numerator, huge.denominator) == (10**400, 1)
    assert (binary.numerator, binary.denominator) == (0.1).as_integer_ratio()


def test_exact_number_reduces_normalizes_and_compares_equivalent_ratios():
    assert ExactNumber.from_ratio(2, 4) == ExactNumber.from_ratio(1, 2)
    assert ExactNumber.from_ratio(1, -2) == ExactNumber.from_ratio(-1, 2)
    assert ExactNumber.from_ratio(-2, -4) == ExactNumber.from_ratio(1, 2)
    assert ExactNumber.from_value(0) == ExactNumber.from_value(-0.0)
    assert ExactNumber.from_value(-0.0).model_dump() == {"numerator": 0, "denominator": 1}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_exact_number_rejects_nonfinite_floats(value: float):
    with pytest.raises(ValidationError):
        ExactNumber.from_value(value)


def test_exact_number_rejects_bool_zero_denominator_and_float_ratio_mix():
    with pytest.raises(ValidationError):
        ExactNumber.from_value(True)
    with pytest.raises(ValidationError):
        ExactNumber.from_ratio(1, 0)
    with pytest.raises(ValidationError):
        ExactNumber(numerator=0.5, denominator=2)


def test_exact_number_copy_and_instance_revalidation_reject_zero_denominator():
    number = ExactNumber.from_ratio(1, 2)
    with pytest.raises(ValidationError, match="nonzero"):
        number.model_copy(update={"denominator": 0})

    object.__setattr__(number, "denominator", 0)
    with pytest.raises(ValidationError, match="nonzero"):
        ExactNumber.model_validate(number)


def test_exact_number_rejects_unknown_fields_before_canonicalization():
    with pytest.raises(ValidationError, match="unexpected ExactNumber field"):
        ExactNumber.model_validate(
            {"numerator": 2, "denominator": 4, "unexpected": "must-not-disappear"}
        )


def test_exact_number_is_immutable_and_exposes_no_arithmetic_protocol():
    number = ExactNumber.from_ratio(1, 2)
    with pytest.raises(ValidationError):
        number.numerator = 2
    for operation in ("__add__", "__sub__", "__mul__", "__truediv__"):
        assert operation not in ExactNumber.__dict__


def test_unit_semantics_represent_all_four_frozen_meanings_without_display_synthesis():
    field_value = MethodUnitSemantics(
        kind="FIELD_VALUE", value_unit="degC", declared_result_unit="degC"
    )
    counter_rate = MethodUnitSemantics(
        kind="COUNTER_QUANTITY_PER_SOURCE_TIME",
        numerator_unit="accepted_share_count",
        denominator_time_basis="SOURCE_TIME",
    )
    slope = MethodUnitSemantics(
        kind="VALUE_QUANTITY_PER_HISTORICAL_TIME",
        numerator_unit="H/s",
        denominator_time_basis="HISTORICAL_TIME",
    )
    dimensionless = MethodUnitSemantics(kind="DIMENSIONLESS")
    assert field_value.value_unit == "degC"
    assert counter_rate.declared_result_unit is None
    assert slope.declared_result_unit is None
    assert dimensionless.model_dump()["value_unit"] is None


@pytest.mark.parametrize(
    "data",
    [
        {"kind": "FIELD_VALUE"},
        {"kind": "DIMENSIONLESS", "value_unit": "ratio"},
        {
            "kind": "COUNTER_QUANTITY_PER_SOURCE_TIME",
            "numerator_unit": "count",
            "denominator_time_basis": "HISTORICAL_TIME",
        },
        {
            "kind": "VALUE_QUANTITY_PER_HISTORICAL_TIME",
            "numerator_unit": "H/s",
            "denominator_time_basis": "SOURCE_TIME",
        },
    ],
)
def test_unit_semantics_reject_cross_kind_claims(data: dict[str, object]):
    with pytest.raises(ValidationError):
        MethodUnitSemantics.model_validate(data)


def test_unit_and_evidence_copy_paths_remain_validating():
    unit = MethodUnitSemantics(kind="FIELD_VALUE", value_unit="degC")
    with pytest.raises(ValidationError):
        unit.model_copy(update={"kind": "DIMENSIONLESS"})
    with pytest.raises(ValidationError):
        use(1).model_copy(update={"role": "IGNORED"})


def test_value_result_is_immutable_and_enforces_evidence_accounting():
    result = MethodValueResult(
        configuration=configuration(),
        value=ExactNumber.from_value(7),
        unit_semantics=MethodUnitSemantics(kind="FIELD_VALUE", value_unit="degC"),
        evidence_use=(use(1), use(2, "EXCLUDED")),
        limitations=("method_layer_only",),
    )
    assert result.method_name is MethodName.ARITHMETIC_MEAN
    assert result.method_version is MethodVersion.V1
    assert result.configuration_sha256 == result.configuration.configuration_sha256
    assert result.field_contract_id == "gpu-temperature"
    with pytest.raises(ValidationError):
        result.value = ExactNumber.from_value(8)
    with pytest.raises(ValidationError, match="used evidence"):
        MethodValueResult(
            configuration=configuration(),
            value=ExactNumber.from_value(7),
            unit_semantics=MethodUnitSemantics(kind="FIELD_VALUE", value_unit="degC"),
            evidence_use=(use(1, "EXCLUDED"),),
        )
    with pytest.raises(ValidationError, match="duplicate method evidence"):
        MethodValueResult(
            configuration=configuration(),
            value=ExactNumber.from_value(7),
            unit_semantics=MethodUnitSemantics(kind="FIELD_VALUE", value_unit="degC"),
            evidence_use=(use(1), use(1, "EXCLUDED")),
        )


def test_value_result_copy_revalidates_discriminator_evidence_and_nested_units():
    result = MethodValueResult(
        configuration=configuration(),
        value=ExactNumber.from_value(7),
        unit_semantics=MethodUnitSemantics(kind="FIELD_VALUE", value_unit="degC"),
        evidence_use=(use(1),),
    )
    with pytest.raises(ValidationError):
        result.model_copy(update={"outcome_kind": "NO_RESULT"})
    with pytest.raises(ValidationError, match="used evidence"):
        result.model_copy(update={"evidence_use": (use(1, "EXCLUDED"),)})

    forged_unit = result.unit_semantics.model_copy()
    object.__setattr__(forged_unit, "kind", "DIMENSIONLESS")
    with pytest.raises(ValidationError, match="DIMENSIONLESS"):
        result.model_copy(update={"unit_semantics": forged_unit})


def test_no_result_has_no_value_unit_or_assessment_claim_and_rejects_used_evidence():
    outcome = MethodNoResult(
        configuration=configuration(MethodName.MISSING_FRACTION),
        reason=MethodNoResultReason.MISSING_OPPORTUNITY_AUTHORITY,
        evidence_use=(use(1, "EXCLUDED"),),
        limitations=("opportunity_authority_not_frozen",),
    )
    assert outcome.reason is MethodNoResultReason.MISSING_OPPORTUNITY_AUTHORITY
    assert "value" not in MethodNoResult.model_fields
    assert "unit_semantics" not in MethodNoResult.model_fields
    with pytest.raises(ValidationError, match="cannot claim used evidence"):
        MethodNoResult(
            configuration=configuration(),
            reason=MethodNoResultReason.INSUFFICIENT_CARDINALITY,
            evidence_use=(use(1),),
        )


def test_no_result_copy_cannot_acquire_value_or_value_discriminator():
    outcome = MethodNoResult(
        configuration=configuration(),
        reason=MethodNoResultReason.INSUFFICIENT_CARDINALITY,
    )
    with pytest.raises(ValidationError):
        outcome.model_copy(update={"value": ExactNumber.from_value(5)})
    with pytest.raises(ValidationError):
        outcome.model_copy(update={"outcome_kind": "VALUE"})


def test_result_foundations_contain_no_assessment_snapshot_or_production_fields():
    forbidden = {
        "validity",
        "confidence",
        "uncertainty",
        "degradation_state",
        "estimated_state_field",
        "snapshot",
        "semantic_content_id",
        "production",
        "estimated_at",
        "artifact_id",
    }
    for result_type in (MethodValueResult, MethodNoResult):
        assert forbidden.isdisjoint(result_type.model_fields)


def test_exception_hierarchy_is_specific_and_has_no_generic_precondition_error():
    assert issubclass(MethodConstructionError, MethodError)
    assert issubclass(InvalidMethodConfigurationError, MethodConstructionError)
    assert issubclass(MalformedAuthoritativeInputError, MethodConstructionError)
    assert issubclass(DuplicateObservationIdentityError, MethodConstructionError)
    for error_type in (
        UnknownMethodError,
        UnsupportedMethodVersionError,
        FieldContractBindingError,
        MalformedS3ArtifactError,
        UnsupportedValueKindError,
        ContinuityViolationError,
        MethodResourceLimitError,
        DeterministicArithmeticError,
    ):
        assert issubclass(error_type, MethodOperationError)
    assert not hasattr(methods, "MethodPreconditionError")


def test_r1_exposes_no_method_execution_or_estimator_arithmetic_api():
    for symbol in (
        "compute_method",
        "compute_candidate",
        "mean",
        "median",
        "minimum",
        "maximum",
        "delta",
        "rate",
        "slope",
        "missing_fraction",
        "MethodExecutionLimits",
        "MethodRequest",
        "MethodScope",
        "MethodEvidence",
        "EvidenceComparability",
        "DeclaredConversion",
        "SemanticParameter",
        "SemanticParameterValue",
        "AdaptiveEngine",
        "MathematicalIR",
        "Tensor",
        "GPUExecutionBackend",
    ):
        assert not hasattr(methods, symbol)


R2_T = datetime(2026, 2, 1, tzinfo=UTC)
R2_MAPPING = SubjectMapping(
    mapping_id="mapping-1",
    mapping_version="v1",
    subject_provenance_keys=("configured_index",),
    include_source_instance_in_subject_key=False,
    subjects={"configured_index=0": "gpu_uuid"},
    workload_provenance_keys=(),
    workloads={},
    algorithm_provenance_key=None,
    algorithms={},
)


def r2_observation(index: int, offset: float, **changes: object) -> RuntimeObservation:
    data: dict[str, object] = {
        "observation_id": UUID(int=index),
        "source": Source.NVML,
        "source_instance": "uuid:GPU-1",
        "signal": "temperature_c",
        "value": 40 + index,
        "unit": "degC",
        "observation_time": R2_T + timedelta(seconds=offset),
        "ingestion_time": R2_T + timedelta(seconds=offset),
        "processing_time": R2_T + timedelta(seconds=offset),
        "quality": Quality.VALID,
        "correlation_id": UUID(int=100 + index),
        "provenance": {"configured_index": 0},
    }
    data.update(changes)
    return RuntimeObservation(**data)


def r2_query(contract: FieldEvidenceContract, *, page_size: int = 1) -> EvidenceQueryRequest:
    predecessor_enabled = contract.predecessor_lookback_seconds > 0
    return EvidenceQueryRequest(
        start_time=R2_T - timedelta(seconds=contract.window_seconds),
        end_time=R2_T,
        time_basis=contract.temporal_basis,
        as_of_cutoff=R2_T,
        session_mode=AssociationMode.ALL,
        sources=(Source.NVML,),
        signals=("temperature_c",),
        maximum_filter_terms=8,
        maximum_records=contract.maximum_records,
        maximum_decoded_bytes=contract.maximum_decoded_bytes,
        maximum_scan_records=1_000,
        maximum_scan_bytes=1_000_000,
        page_size=page_size,
        maximum_pages=100,
        predecessor_lookback_seconds=contract.predecessor_lookback_seconds,
        maximum_predecessor_records=10 if predecessor_enabled else 0,
    )


def r2_pages(
    request: EvidenceQueryRequest,
    records: tuple[RuntimeObservation, ...],
    predecessors: tuple[RuntimeObservation, ...] = (),
) -> tuple[EvidenceQueryResult, ...]:
    ordered = tuple(
        sorted(
            records,
            key=lambda record: (
                record.observation_time,
                record.ingestion_time,
                str(record.observation_id),
            ),
        )
    )
    digest = hashlib.sha256(request.model_dump_json().encode("utf-8")).hexdigest()
    chunks = [
        ordered[offset : offset + request.page_size]
        for offset in range(0, len(ordered), request.page_size)
    ] or [()]
    pages: list[EvidenceQueryResult] = []
    for index, chunk in enumerate(chunks):
        has_more = index < len(chunks) - 1
        continuation = (
            EvidenceQueryContinuation(
                request_sha256=digest,
                dataset_watermark="1" * 64,
                next_offset=(index + 1) * request.page_size,
                next_page=index + 1,
                integrity_mac="2" * 64,
            )
            if has_more
            else None
        )
        pages.append(
            EvidenceQueryResult(
                records=chunk,
                predecessors=predecessors if index == 0 else (),
                completeness=(QueryCompleteness.HAS_MORE if has_more else QueryCompleteness.COMPLETE),
                integrity=QueryIntegrity.VERIFIED,
                dataset_watermark="1" * 64,
                request_sha256=digest,
                continuation=continuation,
                total_records=len(ordered),
                decoded_bytes=1_000,
                scanned_records=20,
                scanned_bytes=2_000,
                query_duration_seconds=0.01 + index,
            )
        )
    return tuple(pages)


def r2_conflict_binding(
    records: tuple[RuntimeObservation, ...],
    identities: tuple,
    contract: FieldEvidenceContract,
) -> ConflictBinding:
    identity_map = {identity.observation_id: identity for identity in identities}
    candidates = tuple(
        ComparableEvidence(
            observation_id=record.observation_id,
            source=record.source,
            source_instance=record.source_instance,
            signal=record.signal,
            unit=record.unit,
            value=record.value,
            effective_basis=contract.temporal_basis,
            effective_time=record.observation_time,
            correlation_id=record.correlation_id,
            identity=identity_map[record.observation_id],
        )
        for record in records
    )
    comparison_contract = ComparisonContract(
        contract_id="temperature-comparison",
        contract_version="v1",
        comparison_basis="same_subject_quantity_unit_effective_interval",
        maximum_alignment_seconds=contract.maximum_alignment_seconds,
        quantities=(
            {"quantity_id": "gpu_temperature", "signals": ("temperature_c",)},
        ),
    )
    comparison_request = ComparisonRequest(
        affected_field_key=contract.field_key,
        quantity_id="gpu_temperature",
        expected_identity={"subject_id": contract.subject_scope},
    )
    result = detect_conflicts(
        candidates,
        comparison_contract,
        comparison_request,
        ConflictDetectionConfig(maximum_candidates=16),
    )
    return ConflictBinding(
        comparison_contract=comparison_contract,
        comparison_request=comparison_request,
        candidates=candidates,
        result=result,
    )


def r2_bundle_data(
    *,
    records: tuple[RuntimeObservation, ...] | None = None,
    predecessors: tuple[RuntimeObservation, ...] = (),
    contract: FieldEvidenceContract | None = None,
    include_conflict: bool = False,
    page_size: int = 1,
) -> dict[str, object]:
    field = contract or field_contract()
    primary = records if records is not None else (
        r2_observation(1, -20),
        r2_observation(2, -10),
    )
    all_records = predecessors + primary
    identities = resolve_identities(
        all_records,
        R2_MAPPING,
        SubjectResolutionConfig(maximum_observations=100),
    )
    admissions = assess_admission(
        all_records,
        R2_T,
        field,
        AdmissionConfig(maximum_observations=100),
    )
    continuity_contract = ContinuityContract(
        contract_id=field.contract_id,
        contract_version=field.contract_version,
        continuity_rule=field.continuity_rule,
        ordering_basis=field.temporal_basis,
        maximum_gap_seconds=field.maximum_gap_seconds,
        counter_semantics=None,
        honor_recorded_discontinuity=False,
        minimum_segment_samples=field.minimum_samples,
        minimum_segment_elapsed_seconds=field.minimum_span_seconds,
    )
    identity_map = {identity.observation_id: identity for identity in identities}
    continuity_result = segment_evidence(
        tuple(
            ScopedObservation(record=record, identity=identity_map[record.observation_id])
            for record in all_records
        ),
        continuity_contract,
        ContinuityConfig(maximum_observations=100),
    )
    query = r2_query(field, page_size=page_size)
    bindings = (
        (r2_conflict_binding(primary, identities, field),)
        if include_conflict
        else ()
    )
    return {
        "field_request": FieldRequest(
            field_key=field.field_key,
            subject_scope=field.subject_scope,
        ),
        "field_contract": field,
        "evidence_query_request": query,
        "evidence_query_results": r2_pages(query, primary, predecessors),
        "admissions": admissions,
        "identities": identities,
        "continuity_contract": continuity_contract,
        "continuity_result": continuity_result,
        "conflict_bindings": bindings,
    }


def r2_bundle(**changes: object) -> AuthoritativeMethodInput:
    data = r2_bundle_data()
    data.update(changes)
    return AuthoritativeMethodInput(**data)


def test_r2a_pristine_bundle_exposes_only_derived_read_only_authority():
    wrapper = AuthoritativeMethodInput(**r2_bundle_data(include_conflict=True))

    assert wrapper.state_reference_time == R2_T
    assert tuple(record.observation_id for record in wrapper.primary_observations) == (
        UUID(int=1),
        UUID(int=2),
    )
    assert isinstance(wrapper.observations_by_id, MappingProxyType)
    assert isinstance(wrapper.admission_map, MappingProxyType)
    assert isinstance(wrapper.identity_map, MappingProxyType)
    assert isinstance(wrapper.observation_segment_index, MappingProxyType)
    assert wrapper.field_contract.estimand == "GPU temperature at reference time"
    assert wrapper.conflict_bindings[0].candidates[0].observation_id == UUID(int=1)


def test_r2a_empty_complete_query_recovers_t_without_a_second_authoritative_time():
    wrapper = AuthoritativeMethodInput(**r2_bundle_data(records=()))

    assert wrapper.state_reference_time == R2_T
    assert wrapper.primary_observations == ()
    assert wrapper.predecessor_observations == ()
    assert "state_reference_time" not in AuthoritativeMethodInput.model_fields


def test_r2a_multi_page_reconstruction_is_permutation_invariant():
    data = r2_bundle_data(include_conflict=True)
    canonical = AuthoritativeMethodInput(**data)
    permuted = AuthoritativeMethodInput(
        **{
            **data,
            "evidence_query_results": tuple(reversed(data["evidence_query_results"])),
            "admissions": tuple(reversed(data["admissions"])),
            "identities": tuple(reversed(data["identities"])),
            "conflict_bindings": tuple(reversed(data["conflict_bindings"])),
        }
    )

    assert permuted == canonical
    assert permuted.canonical_page_order[0].completeness == QueryCompleteness.HAS_MORE


@pytest.mark.parametrize("mutation", ["request_hash", "watermark", "missing_page", "gap"])
def test_r2a_rejects_malformed_page_collection(mutation: str):
    data = r2_bundle_data(records=(r2_observation(1, -25), r2_observation(2, -15), r2_observation(3, -5)))
    pages = list(data["evidence_query_results"])
    if mutation == "request_hash":
        pages[0] = pages[0].model_copy(update={"request_sha256": "f" * 64})
    elif mutation == "watermark":
        pages[1] = pages[1].model_copy(update={"dataset_watermark": "e" * 64})
    elif mutation == "missing_page":
        pages.pop(1)
    else:
        continuation = pages[0].continuation
        assert continuation is not None
        pages[0] = pages[0].model_copy(
            update={"continuation": continuation.model_copy(update={"next_page": 2})}
        )
    with pytest.raises(MalformedAuthoritativeInputError):
        AuthoritativeMethodInput(**{**data, "evidence_query_results": tuple(pages)})


@pytest.mark.parametrize(
    ("metric", "request_limit"),
    (
        ("scanned_records", "maximum_scan_records"),
        ("scanned_bytes", "maximum_scan_bytes"),
    ),
)
def test_r2a_enforces_authoritative_scan_budgets(metric: str, request_limit: str):
    data = r2_bundle_data(records=(r2_observation(1, -10),))
    request = data["evidence_query_request"]
    page = data["evidence_query_results"][0]
    exact = page.model_copy(update={metric: getattr(request, request_limit)})
    AuthoritativeMethodInput(**{**data, "evidence_query_results": (exact,)})

    changed = page.model_copy(update={metric: getattr(request, request_limit) + 1})

    with pytest.raises(MethodResourceLimitError):
        AuthoritativeMethodInput(**{**data, "evidence_query_results": (changed,)})


@pytest.mark.parametrize("metric", ("scanned_records", "scanned_bytes"))
def test_r2a_requires_stable_cumulative_scan_metadata_but_ignores_duration(metric: str):
    data = r2_bundle_data(
        records=(
            r2_observation(1, -25),
            r2_observation(2, -15),
            r2_observation(3, -5),
        )
    )
    pages = list(data["evidence_query_results"])
    pages = [
        page.model_copy(update={"query_duration_seconds": float(index + 1) * 100})
        for index, page in enumerate(pages)
    ]
    AuthoritativeMethodInput(**{**data, "evidence_query_results": tuple(pages)})

    pages[1] = pages[1].model_copy(update={metric: getattr(pages[1], metric) + 1})
    with pytest.raises(MalformedAuthoritativeInputError):
        AuthoritativeMethodInput(**{**data, "evidence_query_results": tuple(pages)})


@pytest.mark.parametrize(
    "mutation",
    ("nonfirst_predecessor", "terminal_completeness", "record_accounting", "transport_order"),
)
def test_r2a_rejects_page_contract_contradictions(mutation: str):
    data = r2_bundle_data(
        records=(
            r2_observation(1, -25),
            r2_observation(2, -15),
            r2_observation(3, -5),
        )
    )
    pages = list(data["evidence_query_results"])
    if mutation == "nonfirst_predecessor":
        pages[1] = pages[1].model_copy(
            update={"predecessors": (r2_observation(9, -35),)}
        )
    elif mutation == "terminal_completeness":
        pages[-1] = pages[-1].model_copy(update={"completeness": QueryCompleteness.HAS_MORE})
    elif mutation == "record_accounting":
        pages[0] = pages[0].model_copy(update={"records": ()})
    else:
        pages[0] = pages[0].model_copy(update={"records": pages[1].records})
        pages[1] = pages[1].model_copy(update={"records": data["evidence_query_results"][0].records})

    with pytest.raises(MalformedAuthoritativeInputError):
        AuthoritativeMethodInput(**{**data, "evidence_query_results": tuple(pages)})


def test_r2a_rejects_invalid_predecessor_placement_and_duplicate_observation_identity():
    contract = field_contract(predecessor_lookback_seconds=10)
    predecessor = r2_observation(9, -35)
    data = r2_bundle_data(contract=contract, predecessors=(predecessor,))
    pages = list(data["evidence_query_results"])
    pages[0] = pages[0].model_copy(update={"predecessors": (r2_observation(10, -50),)})
    with pytest.raises(MalformedAuthoritativeInputError):
        AuthoritativeMethodInput(**{**data, "evidence_query_results": tuple(pages)})

    duplicate_data = r2_bundle_data()
    duplicate_pages = list(duplicate_data["evidence_query_results"])
    duplicate_pages[1] = duplicate_pages[1].model_copy(
        update={"records": duplicate_pages[0].records}
    )
    with pytest.raises(DuplicateObservationIdentityError):
        AuthoritativeMethodInput(
            **{**duplicate_data, "evidence_query_results": tuple(duplicate_pages)}
        )


@pytest.mark.parametrize(
    "mutation",
    ("missing", "duplicate", "unknown", "contract", "window", "preserved_state"),
)
def test_r2a_admission_exact_one_contract_time_and_state_binding(mutation: str):
    data = r2_bundle_data()
    admissions = list(data["admissions"])
    if mutation == "missing":
        admissions.pop()
    elif mutation == "duplicate":
        admissions.append(admissions[0])
    elif mutation == "unknown":
        admissions[0] = admissions[0].model_copy(update={"observation_id": UUID(int=99)})
    elif mutation == "contract":
        admissions[0] = admissions[0].model_copy(update={"field_contract_version": "v2"})
    elif mutation == "window":
        admissions[0] = admissions[0].model_copy(
            update={"window_end": R2_T - timedelta(seconds=1)}
        )
    else:
        admissions[0] = admissions[0].model_copy(update={"input_quality": Quality.UNKNOWN})
    with pytest.raises(MalformedS3ArtifactError):
        AuthoritativeMethodInput(**{**data, "admissions": tuple(admissions)})


@pytest.mark.parametrize("mutation", ("missing", "duplicate", "unknown", "mixed_mapping"))
def test_r2a_identity_exact_one_and_mapping_binding(mutation: str):
    data = r2_bundle_data()
    identities = list(data["identities"])
    if mutation == "missing":
        identities.pop()
    elif mutation == "duplicate":
        identities.append(identities[0])
    elif mutation == "unknown":
        identities[0] = identities[0].model_copy(update={"observation_id": UUID(int=99)})
    else:
        identities[0] = identities[0].model_copy(update={"mapping_version": "v2"})
    with pytest.raises(MalformedS3ArtifactError):
        AuthoritativeMethodInput(**{**data, "identities": tuple(identities)})


def test_r2a_unresolved_identity_is_valid_authoritative_state():
    record = r2_observation(1, -10, provenance={})
    wrapper = AuthoritativeMethodInput(**r2_bundle_data(records=(record,)))

    assert wrapper.identities[0].unresolved_components == ("subject",)
    assert wrapper.continuity_result.segments == ()
    assert wrapper.continuity_result.unassigned[0].observation_id == record.observation_id


@pytest.mark.parametrize(
    "mutation",
    ("contract", "unknown", "duplicate", "assigned_unassigned", "missing", "order", "provenance"),
)
def test_r2a_continuity_structural_binding(mutation: str):
    data = r2_bundle_data()
    result = data["continuity_result"]
    segment = result.segments[0]
    if mutation == "contract":
        result = result.model_copy(update={"contract_version": "v2"})
    elif mutation == "unknown":
        changed = segment.model_copy(
            update={
                "anchor_observation_id": UUID(int=99),
                "observation_ids": (UUID(int=99), UUID(int=2)),
                "boundary": segment.boundary.model_copy(update={"observation_id": UUID(int=99)}),
            }
        )
        result = result.model_copy(update={"segments": (changed,), "boundaries": (changed.boundary,)})
    elif mutation == "duplicate":
        changed = segment.model_copy(update={"observation_ids": (UUID(int=1), UUID(int=1))})
        result = result.model_copy(update={"segments": (changed,)})
    elif mutation == "assigned_unassigned":
        result = result.model_copy(
            update={
                "unassigned": (
                    UnassignedEvidence(
                        observation_id=UUID(int=1),
                        reason="UNRESOLVED_IDENTITY_CONFLICT",
                        detail="adversarial fixture",
                    ),
                )
            }
        )
    elif mutation == "missing":
        changed = segment.model_copy(update={"observation_ids": (UUID(int=1),)})
        result = result.model_copy(update={"segments": (changed,)})
    elif mutation == "order":
        changed_boundary = segment.boundary.model_copy(update={"observation_id": UUID(int=2)})
        changed = segment.model_copy(
            update={
                "anchor_observation_id": UUID(int=2),
                "observation_ids": (UUID(int=2), UUID(int=1)),
                "boundary": changed_boundary,
            }
        )
        result = result.model_copy(update={"segments": (changed,), "boundaries": (changed_boundary,)})
    else:
        changed = segment.model_copy(update={"source": Source.SRBMINER_HTTP})
        result = result.model_copy(update={"segments": (changed,)})
    with pytest.raises(MalformedS3ArtifactError):
        AuthoritativeMethodInput(**{**data, "continuity_result": result})


def test_r2a_recomputes_upstream_produced_deterministic_segment_identity():
    data = r2_bundle_data()
    AuthoritativeMethodInput(**data)
    result = data["continuity_result"]
    segment = result.segments[0]
    changed_boundary = segment.boundary.model_copy(update={"segment_id": "f" * 64})
    changed_segment = segment.model_copy(
        update={"segment_id": "f" * 64, "boundary": changed_boundary}
    )
    changed_result = result.model_copy(
        update={"segments": (changed_segment,), "boundaries": (changed_boundary,)}
    )

    with pytest.raises(MalformedS3ArtifactError):
        AuthoritativeMethodInput(**{**data, "continuity_result": changed_result})


@pytest.mark.parametrize(
    "mutation",
    (
        "first_previous",
        "first_elapsed",
        "nonadjacent_previous",
        "elapsed",
        "segment_start_reason",
    ),
)
def test_r2a_verifies_upstream_continuity_boundary_chain(mutation: str):
    contract = field_contract(maximum_gap_seconds=5)
    data = r2_bundle_data(
        contract=contract,
        records=(
            r2_observation(1, -25),
            r2_observation(2, -15),
            r2_observation(3, -5),
        ),
    )
    AuthoritativeMethodInput(**data)
    result = data["continuity_result"]
    segments = list(result.segments)
    target_index = 0 if mutation in {"first_previous", "first_elapsed"} else 2
    target = segments[target_index]
    if mutation == "first_previous":
        boundary = target.boundary.model_copy(update={"previous_observation_id": UUID(int=3)})
    elif mutation == "first_elapsed":
        boundary = target.boundary.model_copy(update={"elapsed_seconds": 0.0})
    elif mutation == "nonadjacent_previous":
        boundary = target.boundary.model_copy(update={"previous_observation_id": UUID(int=1)})
    elif mutation == "elapsed":
        assert target.boundary.elapsed_seconds is not None
        boundary = target.boundary.model_copy(
            update={"elapsed_seconds": target.boundary.elapsed_seconds + 1}
        )
    else:
        boundary = target.boundary.model_copy(update={"reasons": (BreakReason.SEGMENT_START,)})
    segments[target_index] = target.model_copy(update={"boundary": boundary})
    changed_result = result.model_copy(
        update={
            "segments": tuple(segments),
            "boundaries": tuple(segment.boundary for segment in segments),
        }
    )

    with pytest.raises(MalformedS3ArtifactError):
        AuthoritativeMethodInput(**{**data, "continuity_result": changed_result})


def test_r2a_accepts_producer_boundary_reset_for_each_stream():
    data = r2_bundle_data(
        records=(
            r2_observation(1, -10),
            r2_observation(2, -10, source_instance="uuid:GPU-2"),
        )
    )
    wrapper = AuthoritativeMethodInput(**data)

    assert len(wrapper.continuity_result.segments) == 2
    for segment in wrapper.continuity_result.segments:
        assert segment.boundary.previous_observation_id is None
        assert segment.boundary.elapsed_seconds is None
        assert segment.boundary.reasons == (BreakReason.SEGMENT_START,)


def test_r2a_requires_producer_canonical_unassigned_order():
    records = (
        r2_observation(1, -10, provenance={}),
        r2_observation(2, -10, provenance={}),
    )
    data = r2_bundle_data(records=records)
    producer_result = data["continuity_result"]
    wrapper = AuthoritativeMethodInput(**data)

    assert tuple(item.observation_id for item in wrapper.continuity_result.unassigned) == (
        UUID(int=1),
        UUID(int=2),
    )
    reordered = producer_result.model_copy(
        update={"unassigned": tuple(reversed(producer_result.unassigned))}
    )
    with pytest.raises(MalformedS3ArtifactError):
        AuthoritativeMethodInput(**{**data, "continuity_result": reordered})


def test_r2a_requires_full_producer_segment_order_for_equal_time_anchors():
    records = (
        r2_observation(1, -10, provenance={"configured_index": 0}),
        r2_observation(2, -10, provenance={"configured_index": 1}),
    )
    mapping = R2_MAPPING.model_copy(
        update={
            "subjects": {
                "configured_index=0": "gpu-0",
                "configured_index=1": "gpu-1",
            }
        }
    )
    data = r2_bundle_data(records=records)
    identities = resolve_identities(
        records,
        mapping,
        SubjectResolutionConfig(maximum_observations=100),
    )
    identity_map = {identity.observation_id: identity for identity in identities}
    continuity_result = segment_evidence(
        tuple(
            ScopedObservation(record=record, identity=identity_map[record.observation_id])
            for record in records
        ),
        data["continuity_contract"],
        ContinuityConfig(maximum_observations=100),
    )
    data.update({"identities": identities, "continuity_result": continuity_result})
    wrapper = AuthoritativeMethodInput(**data)
    assert tuple(segment.anchor_observation_id for segment in wrapper.continuity_result.segments) == (
        UUID(int=1),
        UUID(int=2),
    )

    first, second = continuity_result.segments
    reversed_first_boundary = second.boundary.model_copy(
        update={
            "previous_observation_id": None,
            "elapsed_seconds": None,
            "reasons": (BreakReason.SEGMENT_START,),
            "evidence": (),
        }
    )
    reversed_second_boundary = first.boundary.model_copy(
        update={
            "previous_observation_id": second.observation_ids[-1],
            "elapsed_seconds": 0.0,
            "reasons": second.boundary.reasons,
            "evidence": second.boundary.evidence,
        }
    )
    reversed_first = second.model_copy(
        update={"segment_index": 0, "boundary": reversed_first_boundary}
    )
    reversed_second = first.model_copy(
        update={"segment_index": 1, "boundary": reversed_second_boundary}
    )
    reordered = continuity_result.model_copy(
        update={
            "segments": (reversed_first, reversed_second),
            "boundaries": (reversed_first_boundary, reversed_second_boundary),
        }
    )

    with pytest.raises(MalformedS3ArtifactError):
        AuthoritativeMethodInput(**{**data, "continuity_result": reordered})


def test_r2a_valid_conflict_binding_and_no_global_participant_disjointness():
    data = r2_bundle_data(include_conflict=True)
    binding = data["conflict_bindings"][0]
    wrapper = AuthoritativeMethodInput(
        **{**data, "conflict_bindings": (binding, binding)}
    )

    assert len(wrapper.conflict_bindings) == 2
    assert wrapper.conflict_bindings[0].result.contract_id == "temperature-comparison"


def r2_agreement_data(
    first_value: object = 7,
    second_value: object = 7,
) -> dict[str, object]:
    return r2_bundle_data(
        records=(
            r2_observation(1, -10, value=first_value),
            r2_observation(2, -10, source_instance="uuid:GPU-2", value=second_value),
        ),
        include_conflict=True,
    )


@pytest.mark.parametrize(
    ("first_value", "second_value"),
    (
        ([1], [1.0]),
        ([True], [1]),
        ({"x": 1}, {"x": 1.0}),
        ({"x": True}, {"x": 1}),
        (1, 1.0),
    ),
)
def test_r2a_agreement_equality_matches_accepted_s3_semantics(
    first_value: object,
    second_value: object,
):
    data = r2_agreement_data(first_value, second_value)
    producer_result = data["conflict_bindings"][0].result

    assert producer_result.conflicts == ()
    assert len(producer_result.agreements) == 1
    wrapper = AuthoritativeMethodInput(**data)
    assert wrapper.conflict_bindings[0].result == producer_result


@pytest.mark.parametrize(
    ("first_value", "second_value"),
    ((True, 1), ([1], {"0": 1})),
)
def test_r2a_nonagreement_matches_accepted_s3_semantics(
    first_value: object,
    second_value: object,
):
    data = r2_agreement_data(first_value, second_value)
    producer_result = data["conflict_bindings"][0].result

    assert producer_result.agreements == ()
    assert len(producer_result.conflicts) == 1
    wrapper = AuthoritativeMethodInput(**data)
    assert wrapper.conflict_bindings[0].result == producer_result


@pytest.mark.parametrize("mutation", ("participant_order", "source_streams"))
def test_r2a_verifies_upstream_agreement_order_and_stream_provenance(mutation: str):
    data = r2_agreement_data()
    binding = data["conflict_bindings"][0]
    agreement = binding.result.agreements[0]
    if mutation == "participant_order":
        changed_agreement = agreement.model_copy(
            update={"participant_evidence_ids": tuple(reversed(agreement.participant_evidence_ids))}
        )
    else:
        changed_agreement = agreement.model_copy(
            update={"source_streams": ("NVML:forged-1", "NVML:forged-2")}
        )
    changed_result = binding.result.model_copy(update={"agreements": (changed_agreement,)})

    with pytest.raises(MalformedS3ArtifactError):
        ConflictBinding(
            comparison_contract=binding.comparison_contract,
            comparison_request=binding.comparison_request,
            candidates=binding.candidates,
            result=changed_result,
        )


def test_r2a_recomputes_upstream_produced_deterministic_conflict_identity():
    data = r2_bundle_data(
        records=(
            r2_observation(1, -10, value=7),
            r2_observation(2, -10, source_instance="uuid:GPU-2", value=8),
        ),
        include_conflict=True,
    )
    AuthoritativeMethodInput(**data)
    binding = data["conflict_bindings"][0]
    conflict = binding.result.conflicts[0]
    changed_conflict = conflict.model_copy(update={"conflict_id": UUID(int=999)})
    changed_result = binding.result.model_copy(update={"conflicts": (changed_conflict,)})

    with pytest.raises(MalformedS3ArtifactError):
        ConflictBinding(
            comparison_contract=binding.comparison_contract,
            comparison_request=binding.comparison_request,
            candidates=binding.candidates,
            result=changed_result,
        )


def test_r2a_requires_producer_canonical_conflict_participant_order():
    data = r2_bundle_data(
        records=(
            r2_observation(1, -10, value=7),
            r2_observation(2, -10, source_instance="uuid:GPU-2", value=8),
        ),
        include_conflict=True,
    )
    wrapper = AuthoritativeMethodInput(**data)
    binding = data["conflict_bindings"][0]
    conflict = binding.result.conflicts[0]
    assert wrapper.conflict_bindings[0].result.conflicts[0] == conflict

    reordered_conflict = conflict.model_copy(
        update={
            "participant_evidence_ids": tuple(reversed(conflict.participant_evidence_ids))
        }
    )
    reordered_result = binding.result.model_copy(update={"conflicts": (reordered_conflict,)})
    with pytest.raises(MalformedS3ArtifactError):
        ConflictBinding(
            comparison_contract=binding.comparison_contract,
            comparison_request=binding.comparison_request,
            candidates=binding.candidates,
            result=reordered_result,
        )


def test_r2a_conflict_binding_rejects_duplicate_candidate_observation_identity():
    binding = r2_bundle_data(include_conflict=True)["conflict_bindings"][0]

    with pytest.raises(DuplicateObservationIdentityError):
        ConflictBinding(
            comparison_contract=binding.comparison_contract,
            comparison_request=binding.comparison_request,
            candidates=(binding.candidates[0], binding.candidates[0]),
            result=binding.result,
        )


@pytest.mark.parametrize(
    "mutation",
    ("contract", "field", "quantity", "unknown_participant", "duplicate_accounting"),
)
def test_r2a_conflict_binding_rejects_structural_contradictions(mutation: str):
    data = r2_bundle_data(include_conflict=True)
    binding = data["conflict_bindings"][0]
    result = binding.result
    request = binding.comparison_request
    if mutation == "contract":
        result = result.model_copy(update={"contract_version": "v2"})
    elif mutation == "field":
        request = request.model_copy(update={"affected_field_key": "other_field"})
    elif mutation == "quantity":
        request = request.model_copy(update={"quantity_id": "other_quantity"})
    elif mutation == "unknown_participant":
        result = result.model_copy(
            update={
                "conflicts": (),
                "agreements": (),
                "not_compared": (
                    NotComparedEvidence(
                        observation_id=UUID(int=99),
                        reason="not_compared",
                        detail="adversarial fixture",
                    ),
                ),
            }
        )
    else:
        identifier = binding.candidates[0].observation_id
        result = result.model_copy(
            update={
                "conflicts": (),
                "agreements": (),
                "not_compared": (
                    NotComparedEvidence(
                        observation_id=identifier,
                        reason="one",
                        detail="first",
                    ),
                    NotComparedEvidence(
                        observation_id=identifier,
                        reason="two",
                        detail="second",
                    ),
                ),
            }
        )
    with pytest.raises(MalformedS3ArtifactError):
        ConflictBinding(
            comparison_contract=binding.comparison_contract,
            comparison_request=request,
            candidates=binding.candidates,
            result=result,
        )


def test_r2a_rejects_candidate_projection_contradiction():
    data = r2_bundle_data(include_conflict=True)
    binding = data["conflict_bindings"][0]
    changed = binding.candidates[0].model_copy(update={"correlation_id": UUID(int=999)})
    malformed_binding = binding.model_copy(
        update={"candidates": (changed, *binding.candidates[1:])}
    )

    with pytest.raises(MalformedS3ArtifactError):
        AuthoritativeMethodInput(**{**data, "conflict_bindings": (malformed_binding,)})


def test_r2a_rejects_recursive_candidate_raw_projection_type_drift():
    value = {"nested": [True, 1, 1.0]}
    data = r2_bundle_data(
        records=(
            r2_observation(1, -10, value=value),
            r2_observation(2, -10, source_instance="uuid:GPU-2", value=value),
        ),
        include_conflict=True,
    )
    binding = data["conflict_bindings"][0]
    changed = binding.candidates[0].model_copy(
        update={"value": {"nested": [1, 1, 1.0]}}
    )
    malformed_binding = binding.model_copy(
        update={"candidates": (changed, *binding.candidates[1:])}
    )

    with pytest.raises(MalformedS3ArtifactError):
        AuthoritativeMethodInput(**{**data, "conflict_bindings": (malformed_binding,)})


def test_r2a_deep_immutability_detaches_original_and_outbound_nested_authority():
    records = (
        r2_observation(
            1,
            -10,
            value={"samples": [1, 2]},
            quality_metadata={"checks": [{"ok": True}]},
            provenance={"configured_index": 0, "path": ["a", "b"]},
        ),
        r2_observation(
            2,
            -10,
            source_instance="uuid:GPU-2",
            value={"samples": [1, 2]},
        ),
    )
    caller_record_value = records[0].value
    caller_quality_metadata = records[0].quality_metadata
    caller_provenance = records[0].provenance
    data = r2_bundle_data(records=records)
    field = data["field_contract"]
    identity_map = {identity.observation_id: identity for identity in data["identities"]}
    candidates = tuple(
        ComparableEvidence(
            observation_id=record.observation_id,
            source=record.source,
            source_instance=record.source_instance,
            signal=record.signal,
            unit=record.unit,
            value=record.value,
            effective_basis=field.temporal_basis,
            effective_time=record.observation_time,
            correlation_id=record.correlation_id,
            identity=identity_map[record.observation_id],
        )
        for record in records
    )
    comparison_contract = ComparisonContract(
        contract_id="temperature-comparison",
        contract_version="v1",
        comparison_basis="same_subject_quantity_unit_effective_interval",
        maximum_alignment_seconds=field.maximum_alignment_seconds,
        quantities=({"quantity_id": "gpu_temperature", "signals": ("temperature_c",)},),
    )
    comparison_request = ComparisonRequest(
        affected_field_key=field.field_key,
        quantity_id="gpu_temperature",
        expected_identity={"subject_id": field.subject_scope},
    )
    producer_result = detect_conflicts(
        candidates,
        comparison_contract,
        comparison_request,
        ConflictDetectionConfig(maximum_candidates=16),
    )
    assert producer_result.conflicts == ()
    assert len(producer_result.agreements) >= 1
    participant_ids = tuple(sorted((record.observation_id for record in records), key=str))
    producer_agreement = next(
        (
            agreement
            for agreement in producer_result.agreements
            if agreement.participant_evidence_ids == participant_ids
        ),
        None,
    )
    assert producer_agreement is not None
    assert producer_agreement.agreed_value == {"samples": [1, 2]}
    caller_binding = ConflictBinding(
        comparison_contract=comparison_contract,
        comparison_request=comparison_request,
        candidates=candidates,
        result=producer_result,
    )
    data["conflict_bindings"] = (caller_binding,)
    caller_candidate_value = candidates[0].value
    caller_agreement_value = producer_agreement.agreed_value
    wrapper = AuthoritativeMethodInput(**data)

    assert isinstance(caller_record_value, dict)
    assert isinstance(caller_quality_metadata, dict)
    assert isinstance(caller_provenance, dict)
    assert isinstance(caller_candidate_value, dict)
    assert isinstance(caller_agreement_value, dict)
    caller_record_value["samples"].append(3)
    caller_quality_metadata["checks"][0]["ok"] = False
    caller_provenance["path"].append("c")
    caller_candidate_value["samples"].append(4)
    caller_agreement_value["samples"].append(5)

    assert caller_binding.candidates[0].value == {"samples": [1, 2]}
    assert caller_binding.result.agreements[0].agreed_value == {"samples": [1, 2]}
    assert wrapper.primary_observations[0].value == {"samples": [1, 2]}
    assert wrapper.primary_observations[0].quality_metadata == {"checks": [{"ok": True}]}
    assert wrapper.primary_observations[0].provenance["path"] == ["a", "b"]
    assert wrapper.conflict_bindings[0].candidates[0].value == {"samples": [1, 2]}
    assert wrapper.conflict_bindings[0].result.agreements[0].agreed_value == {
        "samples": [1, 2]
    }

    outbound_record = wrapper.evidence_query_results[0].records[0]
    outbound_record.value["samples"].append(6)
    outbound_record.quality_metadata["checks"][0]["ok"] = False
    outbound_record.provenance["path"].append("d")
    outbound_candidate = caller_binding.candidates[0]
    outbound_candidate.value["samples"].append(7)
    outbound_agreement = caller_binding.result.agreements[0]
    outbound_agreement.agreed_value["samples"].append(8)

    assert caller_binding.candidates[0].value == {"samples": [1, 2]}
    assert caller_binding.result.agreements[0].agreed_value == {"samples": [1, 2]}
    assert wrapper.primary_observations[0].value == {"samples": [1, 2]}
    assert wrapper.primary_observations[0].quality_metadata == {"checks": [{"ok": True}]}
    assert wrapper.primary_observations[0].provenance["path"] == ["a", "b"]
    assert wrapper.conflict_bindings[0].candidates[0].value == {"samples": [1, 2]}
    assert wrapper.conflict_bindings[0].result.agreements[0].agreed_value == {
        "samples": [1, 2]
    }


def test_r2a_deep_immutability_closes_derived_vars_iteration_and_copy_surfaces():
    record = r2_observation(1, -10, value={"samples": [1, 2]})
    wrapper = AuthoritativeMethodInput(**r2_bundle_data(records=(record,)))
    original_python = wrapper.model_dump(mode="python")

    wrapper.primary_observations[0].value["samples"].append(3)
    wrapper.observations_by_id[record.observation_id].value["samples"].append(4)
    vars(wrapper)["evidence_query_results"][0].records[0].value["samples"].append(5)
    dict(wrapper)["evidence_query_results"][0].records[0].value["samples"].append(6)

    assert wrapper.primary_observations[0].value == {"samples": [1, 2]}

    shallow = copy.copy(wrapper)
    deep = copy.deepcopy(wrapper)
    direct_deep = wrapper.__deepcopy__()
    assert direct_deep == wrapper
    shallow_state = object.__getattribute__(shallow, "__dict__")
    deep_state = object.__getattribute__(deep, "__dict__")
    direct_deep_state = object.__getattribute__(direct_deep, "__dict__")
    shallow_state["evidence_query_results"][0].records[0].value["samples"].append(7)
    deep_state["evidence_query_results"][0].records[0].value["samples"].append(8)
    direct_deep_state["evidence_query_results"][0].records[0].value["samples"].append(9)

    assert wrapper.primary_observations[0].value == {"samples": [1, 2]}
    assert shallow.primary_observations[0].value == {"samples": [1, 2, 7]}
    assert deep.primary_observations[0].value == {"samples": [1, 2, 8]}
    assert direct_deep.primary_observations[0].value == {"samples": [1, 2, 9]}
    assert wrapper.model_dump(mode="python") == original_python
    assert isinstance(wrapper.model_dump(mode="python")["evidence_query_results"], tuple)
    assert isinstance(
        wrapper.model_dump(mode="python")["evidence_query_results"][0]["records"][0]["value"],
        dict,
    )
    assert isinstance(
        wrapper.model_dump(mode="python")["evidence_query_results"][0]["records"][0]["value"][
            "samples"
        ],
        list,
    )
    assert wrapper.model_dump_json() == wrapper.model_dump_json()
    assert json.loads(wrapper.model_dump_json()) == wrapper.model_dump(mode="json")


def test_r2a_python_dump_preserves_nested_bool_int_and_float_representation():
    record = r2_observation(1, -10, value={"nested": [True, 1, 1.5]})
    wrapper = AuthoritativeMethodInput(**r2_bundle_data(records=(record,)))

    dumped = wrapper.model_dump(mode="python")
    nested = dumped["evidence_query_results"][0]["records"][0]["value"]["nested"]
    assert type(nested[0]) is bool
    assert type(nested[1]) is int
    assert type(nested[2]) is float


def _oversized_predecessor_payload() -> dict[str, object]:
    return r2_bundle_data(
        contract=field_contract(predecessor_lookback_seconds=1e20),
        records=(),
    )


def _json_payload(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return [_json_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_payload(item) for key, item in value.items()}
    return value


@pytest.mark.parametrize(
    "entrypoint",
    (
        "init",
        "model_validate",
        "model_validate_json",
        "type_adapter_python",
        "type_adapter_json",
    ),
)
def test_r2a_oversized_predecessor_lookback_preserves_typed_error_surface(
    entrypoint: str,
):
    payload = _oversized_predecessor_payload()
    json_entrypoint = entrypoint in {"model_validate_json", "type_adapter_json"}
    submitted = _json_payload(payload) if json_entrypoint else payload

    with pytest.raises(MalformedAuthoritativeInputError):
        if entrypoint == "init":
            AuthoritativeMethodInput(**submitted)
        elif entrypoint == "model_validate":
            AuthoritativeMethodInput.model_validate(submitted)
        elif entrypoint == "model_validate_json":
            AuthoritativeMethodInput.model_validate_json(json.dumps(submitted))
        elif entrypoint == "type_adapter_python":
            TypeAdapter(AuthoritativeMethodInput).validate_python(submitted)
        else:
            TypeAdapter(AuthoritativeMethodInput).validate_json(json.dumps(submitted))


def test_r2a_model_copy_oversized_predecessor_lookback_preserves_typed_error_surface():
    wrapper = AuthoritativeMethodInput(**r2_bundle_data(records=()))
    field = wrapper.field_contract.model_copy(update={"predecessor_lookback_seconds": 1e20})
    request = wrapper.evidence_query_request.model_copy(
        update={
            "predecessor_lookback_seconds": 1e20,
            "maximum_predecessor_records": 10,
        }
    )
    request_sha256 = hashlib.sha256(request.model_dump_json().encode("utf-8")).hexdigest()
    pages = tuple(
        page.model_copy(update={"request_sha256": request_sha256})
        for page in wrapper.evidence_query_results
    )

    with pytest.raises(MalformedAuthoritativeInputError):
        wrapper.model_copy(
            update={
                "field_contract": field,
                "evidence_query_request": request,
                "evidence_query_results": pages,
            }
        )


@pytest.mark.parametrize(
    "entrypoint",
    (
        "init",
        "model_validate",
        "model_validate_json",
        "type_adapter_python",
        "type_adapter_json",
    ),
)
@pytest.mark.parametrize("shape", ("missing", "unexpected"))
@pytest.mark.parametrize(
    ("model_type", "fixture", "required_field", "error_type"),
    (
        (
            AuthoritativeMethodInput,
            lambda: AuthoritativeMethodInput(**r2_bundle_data()),
            "continuity_result",
            MalformedAuthoritativeInputError,
        ),
        (
            ConflictBinding,
            lambda: r2_bundle_data(include_conflict=True)["conflict_bindings"][0],
            "result",
            MalformedS3ArtifactError,
        ),
    ),
)
def test_r2a_structural_shape_errors_preserve_typed_taxonomy(
    entrypoint: str,
    shape: str,
    model_type: type,
    fixture,
    required_field: str,
    error_type: type[MethodError],
):
    canonical = fixture()
    json_entrypoint = entrypoint in {"model_validate_json", "type_adapter_json"}
    payload = canonical.model_dump(mode="json" if json_entrypoint else "python")
    if shape == "missing":
        payload.pop(required_field)
    else:
        payload["unexpected_authority"] = True

    with pytest.raises(error_type):
        if entrypoint == "init":
            model_type(**payload)
        elif entrypoint == "model_validate":
            model_type.model_validate(payload)
        elif entrypoint == "model_validate_json":
            model_type.model_validate_json(json.dumps(payload))
        elif entrypoint == "type_adapter_python":
            TypeAdapter(model_type).validate_python(payload)
        else:
            TypeAdapter(model_type).validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    ("model_type", "error_type"),
    (
        (AuthoritativeMethodInput, MalformedAuthoritativeInputError),
        (ConflictBinding, MalformedS3ArtifactError),
    ),
)
def test_r2a_nonmapping_structure_preserves_typed_taxonomy(model_type: type, error_type: type):
    with pytest.raises(error_type):
        model_type.model_validate([])


def test_r2a_public_models_close_pydantic_bypass_surfaces_and_revalidate_nested_instances():
    data = r2_bundle_data(include_conflict=True)
    wrapper = AuthoritativeMethodInput(**data)
    binding = wrapper.conflict_bindings[0]

    with pytest.raises(MalformedS3ArtifactError):
        wrapper.model_copy(update={"admissions": wrapper.admissions[:-1]})
    with pytest.raises(MalformedS3ArtifactError):
        binding.model_copy(
            update={"result": binding.result.model_copy(update={"contract_version": "v2"})}
        )
    for model in (wrapper, binding):
        with pytest.raises(TypeError, match=r"copy\(\) is disabled"):
            model.copy()
        with pytest.raises(TypeError, match=r"model_construct.*disabled"):
            type(model).model_construct()
        with pytest.raises(TypeError, match=r"model_construct.*disabled"):
            type(model).construct()

    forged_result = binding.result.model_copy()
    object.__setattr__(forged_result, "contract_version", "v2")
    with pytest.raises(MalformedS3ArtifactError):
        ConflictBinding(
            comparison_contract=binding.comparison_contract,
            comparison_request=binding.comparison_request,
            candidates=binding.candidates,
            result=forged_result,
        )


def test_r2a_unknown_fields_are_rejected_and_forbidden_authority_fields_do_not_exist():
    data = r2_bundle_data(include_conflict=True)
    binding = data["conflict_bindings"][0]
    with pytest.raises(MalformedAuthoritativeInputError):
        AuthoritativeMethodInput(**data, comparable=True)
    with pytest.raises(MalformedS3ArtifactError):
        ConflictBinding(
            comparison_contract=binding.comparison_contract,
            comparison_request=binding.comparison_request,
            candidates=binding.candidates,
            result=binding.result,
            winner="NVML",
        )
    forbidden = {
        "observations",
        "state_reference_time",
        "eligible",
        "comparable",
        "same_segment",
        "preferred_provider",
        "winner",
        "support_ids",
        "opportunity_contract",
        "assessment",
        "snapshot",
        "persistence",
        "production_metadata",
    }
    assert forbidden.isdisjoint(AuthoritativeMethodInput.model_fields)
    assert {"comparable", "preferred_provider", "winner"}.isdisjoint(
        ConflictBinding.model_fields
    )


def test_r2b_authoritative_analytical_set_contract_is_closed():
    field = field_contract()
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=field,
    )
    used = MethodEvidenceUse(
        observation_id=UUID(int=1),
        role="USED",
        reason="authoritative_single_stream_support",
    )
    excluded = MethodEvidenceUse(
        observation_id=UUID(int=2),
        role="EXCLUDED",
        reason="excluded_for_test",
    )

    current = AuthoritativeAnalyticalSet(
        configuration=configuration,
        support_view="CURRENT",
        support_observation_ids=(UUID(int=1),),
        evidence_use=(used, excluded),
    )
    assert current.support_observation_ids == (UUID(int=1),)
    assert current.evidence_use == (used, excluded)
    assert current.continuity_segment_id is None

    historical_configuration = build_method_configuration(
        method_name="within_segment_delta",
        method_version="v1",
        field_contract=field,
    )
    historical = AuthoritativeAnalyticalSet(
        configuration=historical_configuration,
        support_view="HISTORICAL",
        support_observation_ids=(UUID(int=1),),
        evidence_use=(used,),
        continuity_segment_id="segment-1",
    )
    assert historical.continuity_segment_id == "segment-1"

    invalid_payloads = (
        {
            "support_observation_ids": (UUID(int=1), UUID(int=1)),
            "evidence_use": (used,),
        },
        {
            "support_observation_ids": (UUID(int=2),),
            "evidence_use": (used, excluded),
        },
        {
            "support_observation_ids": (UUID(int=1),),
            "evidence_use": (excluded,),
        },
        {
            "support_view": "CURRENT",
            "continuity_segment_id": "segment-1",
        },
        {
            "support_view": "HISTORICAL",
            "continuity_segment_id": None,
        },
    )

    base = {
        "configuration": configuration,
        "support_view": "CURRENT",
        "support_observation_ids": (UUID(int=1),),
        "evidence_use": (used,),
        "continuity_segment_id": None,
    }

    for changes in invalid_payloads:
        with pytest.raises(ValidationError):
            AuthoritativeAnalyticalSet(**{**base, **changes})


@pytest.mark.parametrize(
    ("method_name", "expected_view"),
    (
        ("latest_eligible_value", "CURRENT"),
        ("arithmetic_mean", "CURRENT"),
        ("median", "CURRENT"),
        ("min", "CURRENT"),
        ("max", "CURRENT"),
        ("within_segment_delta", "HISTORICAL"),
        ("source_time_counter_rate", "HISTORICAL"),
        ("historical_endpoint_slope", "HISTORICAL"),
        ("missing_fraction", None),
    ),
)
def test_r2b_method_identity_closes_support_view(
    method_name: str,
    expected_view: str | None,
):
    field = field_contract()
    configuration = build_method_configuration(
        method_name=method_name,
        method_version="v1",
        field_contract=field,
    )
    used = MethodEvidenceUse(
        observation_id=UUID(int=1),
        role="USED",
        reason="authoritative_single_stream_support",
    )

    base = {
        "configuration": configuration,
        "support_observation_ids": (UUID(int=1),),
        "evidence_use": (used,),
    }

    if expected_view is None:
        with pytest.raises(ValidationError):
            AuthoritativeAnalyticalSet(
                **base,
                support_view="CURRENT",
            )
        with pytest.raises(ValidationError):
            AuthoritativeAnalyticalSet(
                **base,
                support_view="HISTORICAL",
                continuity_segment_id="segment-1",
            )
        return

    continuity_segment_id = (
        "segment-1" if expected_view == "HISTORICAL" else None
    )
    result = AuthoritativeAnalyticalSet(
        **base,
        support_view=expected_view,
        continuity_segment_id=continuity_segment_id,
    )
    assert result.support_view == expected_view

    wrong_view = "HISTORICAL" if expected_view == "CURRENT" else "CURRENT"
    with pytest.raises(ValidationError):
        AuthoritativeAnalyticalSet(
            **base,
            support_view=wrong_view,
            continuity_segment_id=(
                "segment-1" if wrong_view == "HISTORICAL" else None
            ),
        )

    if expected_view == "HISTORICAL":
        with pytest.raises(ValidationError):
            AuthoritativeAnalyticalSet(
                **base,
                support_view="HISTORICAL",
                continuity_segment_id=None,
            )


def test_r2b_support_configuration_requires_exact_field_contract_binding():
    authoritative = r2_bundle()
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    assert (
        methods._validate_support_configuration(configuration, authoritative)
        == "CURRENT"
    )

    historical = build_method_configuration(
        method_name="within_segment_delta",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )
    assert (
        methods._validate_support_configuration(historical, authoritative)
        == "HISTORICAL"
    )

    missing = build_method_configuration(
        method_name="missing_fraction",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )
    assert methods._validate_support_configuration(missing, authoritative) is None

    wrong_contract = field_contract(
        contract_id="different-contract",
        contract_version="v9",
    )
    mismatched = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=wrong_contract,
    )
    with pytest.raises(FieldContractBindingError):
        methods._validate_support_configuration(mismatched, authoritative)


def test_r2b_initial_support_filter_uses_authoritative_admission_and_subject():
    records = (
        r2_observation(1, -20),
        r2_observation(2, -15, value=None),
        r2_observation(
            3,
            -10,
            provenance={"configured_index": 999},
        ),
    )
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(records=records)
    )

    assert (
        methods._initial_support_exclusion_reason(
            records[0],
            authoritative,
            "CURRENT",
        )
        is None
    )

    admission_reason = methods._initial_support_exclusion_reason(
        records[1],
        authoritative,
        "CURRENT",
    )
    assert admission_reason is not None
    assert admission_reason.startswith("admission:EXCLUDED:")

    identity_reason = methods._initial_support_exclusion_reason(
        records[2],
        authoritative,
        "CURRENT",
    )
    assert identity_reason is not None
    assert identity_reason.startswith("identity:subject:")


def test_r2b_initial_filter_does_not_infer_workload_or_algorithm_requirements():
    authoritative = r2_bundle()
    observation = authoritative.primary_observations[0]
    identity = authoritative.identity_map[observation.observation_id]

    assert identity.workload.status.value == "NOT_DECLARED"
    assert identity.algorithm.status.value == "NOT_DECLARED"

    assert (
        methods._initial_support_exclusion_reason(
            observation,
            authoritative,
            "CURRENT",
        )
        is None
    )


def test_r2b_field_compatibility_accepts_exact_declared_signal_and_unit():
    authoritative = r2_bundle()
    observation = authoritative.primary_observations[0]

    assert (
        methods._field_compatibility_exclusion_reason(
            observation,
            authoritative,
        )
        is None
    )


def test_r2b_field_compatibility_does_not_execute_declared_conversion():
    contract = field_contract(
        allowed_units=("degC", "degF"),
        allowed_conversions=("fahrenheit_to_celsius_v1",),
    )
    observation = r2_observation(
        1,
        -10,
        unit="degF",
    )
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=(observation,),
            contract=contract,
        )
    )

    assert (
        methods._field_compatibility_exclusion_reason(
            authoritative.primary_observations[0],
            authoritative,
        )
        == "unit_conversion_not_authorized"
    )


def test_r2b_undeclared_source_signal_is_rejected_at_the_earliest_authority_boundary():
    observation = r2_observation(
        1,
        -10,
        signal="undeclared_signal",
    )

    with pytest.raises(MalformedAuthoritativeInputError):
        AuthoritativeMethodInput(
            **r2_bundle_data(records=(observation,))
        )

    authoritative = r2_bundle()
    with pytest.raises(MalformedS3ArtifactError):
        methods._field_compatibility_exclusion_reason(
            observation,
            authoritative,
        )


def test_r2b_conflict_disposition_preserves_authoritative_agreement():
    records = (
        r2_observation(
            1,
            -10,
            value=50,
            source_instance="uuid:GPU-A",
        ),
        r2_observation(
            2,
            -10,
            value=50,
            source_instance="uuid:GPU-B",
        ),
    )
    identities = resolve_identities(
        records,
        R2_MAPPING,
        SubjectResolutionConfig(maximum_observations=100),
    )
    binding = r2_conflict_binding(
        records,
        identities,
        field_contract(),
    )

    dispositions = methods._conflict_binding_dispositions(binding)

    assert dispositions[UUID(int=1)] == (
        "AGREEMENT",
        "authoritative_s3_comparable_agreement",
    )
    assert dispositions[UUID(int=2)] == (
        "AGREEMENT",
        "authoritative_s3_comparable_agreement",
    )


def test_r2b_conflict_disposition_preserves_unresolved_value_disagreement():
    records = (
        r2_observation(
            1,
            -10,
            value=50,
            source_instance="uuid:GPU-A",
        ),
        r2_observation(
            2,
            -10,
            value=55,
            source_instance="uuid:GPU-B",
        ),
    )
    identities = resolve_identities(
        records,
        R2_MAPPING,
        SubjectResolutionConfig(maximum_observations=100),
    )
    binding = r2_conflict_binding(
        records,
        identities,
        field_contract(),
    )

    dispositions = methods._conflict_binding_dispositions(binding)

    for observation_id in (UUID(int=1), UUID(int=2)):
        kind, reason = dispositions[observation_id]
        assert kind == "CONFLICT"
        assert reason.startswith(
            "conflict:VALUE_DISAGREEMENT:"
        )


def test_r2b_conflict_disposition_preserves_identity_mismatch_separately():
    records = (
        r2_observation(
            1,
            -10,
            value=50,
            source_instance="uuid:GPU-A",
        ),
        r2_observation(
            2,
            -10,
            value=50,
            source_instance="uuid:GPU-B",
            provenance={"configured_index": 999},
        ),
    )
    identities = resolve_identities(
        records,
        R2_MAPPING,
        SubjectResolutionConfig(maximum_observations=100),
    )
    binding = r2_conflict_binding(
        records,
        identities,
        field_contract(),
    )

    dispositions = methods._conflict_binding_dispositions(binding)

    for observation_id in (UUID(int=1), UUID(int=2)):
        kind, reason = dispositions[observation_id]
        assert kind == "CONFLICT"
        assert reason.startswith(
            "conflict:IDENTITY_MISMATCH:"
        )


def test_r2b_not_compared_never_becomes_agreement():
    records = (
        r2_observation(1, -10),
    )
    identities = resolve_identities(
        records,
        R2_MAPPING,
        SubjectResolutionConfig(maximum_observations=100),
    )
    binding = r2_conflict_binding(
        records,
        identities,
        field_contract(),
    )

    dispositions = methods._conflict_binding_dispositions(binding)

    kind, reason = dispositions[UUID(int=1)]

    assert kind == "NOT_COMPARED"
    assert reason.startswith("not_compared:")


def test_r2b_conflict_disposition_has_no_global_participant_registry():
    shared = r2_observation(1, -10, value=50)

    first_records = (shared,)
    first_identities = resolve_identities(
        first_records,
        R2_MAPPING,
        SubjectResolutionConfig(maximum_observations=100),
    )
    first = r2_conflict_binding(
        first_records,
        first_identities,
        field_contract(),
    )

    second_records = (
        shared,
        r2_observation(
            2,
            -10,
            value=50,
            source_instance="uuid:GPU-B",
        ),
    )
    second_identities = resolve_identities(
        second_records,
        R2_MAPPING,
        SubjectResolutionConfig(maximum_observations=100),
    )
    second = r2_conflict_binding(
        second_records,
        second_identities,
        field_contract(),
    )

    first_dispositions = methods._conflict_binding_dispositions(first)
    second_dispositions = methods._conflict_binding_dispositions(second)

    assert UUID(int=1) in first_dispositions
    assert UUID(int=1) in second_dispositions


def test_r2b_historical_segment_binding_preserves_authoritative_segment_order():
    records = (
        r2_observation(2, -20),
        r2_observation(1, -10),
    )
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(records=records)
    )

    result = methods._historical_segment_binding(
        authoritative,
        (UUID(int=1), UUID(int=2)),
    )

    assert result is not None
    segment_id, ordered_ids = result

    assert segment_id == authoritative.continuity_result.segments[0].segment_id
    assert ordered_ids == (
        UUID(int=2),
        UUID(int=1),
    )


def test_r2b_historical_segment_binding_refuses_cross_segment_support():
    contract = field_contract(
        maximum_gap_seconds=5,
    )
    records = (
        r2_observation(1, -20),
        r2_observation(2, -10),
    )
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=records,
            contract=contract,
        )
    )

    assert len(authoritative.continuity_result.segments) == 2

    assert (
        methods._historical_segment_binding(
            authoritative,
            (UUID(int=1), UUID(int=2)),
        )
        is None
    )


def test_r2b_historical_segment_binding_refuses_insufficient_segment():
    contract = field_contract(
        minimum_samples=3,
    )
    records = (
        r2_observation(1, -20),
        r2_observation(2, -10),
    )
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=records,
            contract=contract,
        )
    )

    assert len(authoritative.continuity_result.segments) == 1
    assert not (
        authoritative.continuity_result
        .segments[0]
        .evidence_sufficient_for_derivation
    )

    assert (
        methods._historical_segment_binding(
            authoritative,
            (UUID(int=1), UUID(int=2)),
        )
        is None
    )


def test_r2b_historical_segment_binding_refuses_unassigned_evidence():
    record = r2_observation(
        1,
        -10,
        provenance={},
    )
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(records=(record,))
    )

    assert authoritative.continuity_result.segments == ()
    assert len(authoritative.continuity_result.unassigned) == 1

    assert (
        methods._historical_segment_binding(
            authoritative,
            (UUID(int=1),),
        )
        is None
    )


def test_r2b_historical_segment_binding_rejects_non_authoritative_identity_input():
    authoritative = r2_bundle()

    with pytest.raises(MalformedS3ArtifactError):
        methods._historical_segment_binding(
            authoritative,
            (UUID(int=1), UUID(int=1)),
        )

    with pytest.raises(MalformedS3ArtifactError):
        methods._historical_segment_binding(
            authoritative,
            (UUID(int=999),),
        )


def test_r2b_current_multi_stream_support_accepts_one_full_authoritative_agreement():
    authoritative = AuthoritativeMethodInput(
        **r2_agreement_data(
            first_value=50,
            second_value=50,
        )
    )
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    result = methods._current_multi_stream_support(
        configuration,
        authoritative,
    )

    assert isinstance(result, AuthoritativeAnalyticalSet)
    assert result.support_view == "CURRENT"
    assert result.support_observation_ids == (
        UUID(int=1),
        UUID(int=2),
    )
    assert tuple(
        item.role
        for item in result.evidence_use
    ) == (
        "USED",
        "USED",
    )
    assert {
        item.reason
        for item in result.evidence_use
    } == {
        "authoritative_s3_comparable_agreement",
    }


def test_r2b_current_multi_stream_support_returns_unresolved_conflict_no_result():
    authoritative = AuthoritativeMethodInput(
        **r2_agreement_data(
            first_value=50,
            second_value=55,
        )
    )
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    result = methods._current_multi_stream_support(
        configuration,
        authoritative,
    )

    assert isinstance(result, MethodNoResult)
    assert result.reason == MethodNoResultReason.UNRESOLVED_CONFLICT
    assert tuple(
        item.role
        for item in result.evidence_use
    ) == (
        "EXCLUDED",
        "EXCLUDED",
    )
    assert all(
        item.reason.startswith("conflict:VALUE_DISAGREEMENT:")
        for item in result.evidence_use
    )


def test_r2b_current_multi_stream_support_does_not_invent_authority_without_binding():
    records = (
        r2_observation(
            1,
            -10,
            source_instance="uuid:GPU-A",
            value=50,
        ),
        r2_observation(
            2,
            -10,
            source_instance="uuid:GPU-B",
            value=50,
        ),
    )
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=records,
            include_conflict=False,
        )
    )
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    result = methods._current_multi_stream_support(
        configuration,
        authoritative,
    )

    assert isinstance(result, MethodNoResult)
    assert (
        result.reason
        == MethodNoResultReason.NO_SINGLE_COMPARABLE_ANALYTICAL_SET
    )
    assert tuple(
        item.observation_id
        for item in result.evidence_use
    ) == (
        UUID(int=1),
        UUID(int=2),
    )
    assert all(
        item.role == "EXCLUDED"
        for item in result.evidence_use
    )
    assert {
        item.reason
        for item in result.evidence_use
    } == {
        "method:no_single_comparable_analytical_set",
    }


def test_r2b_current_multi_stream_redundant_full_authority_same_set_is_not_ambiguity():
    data = r2_agreement_data(
        first_value=50,
        second_value=50,
    )
    first_binding = data["conflict_bindings"][0]

    second_contract = first_binding.comparison_contract.model_copy(
        update={
            "contract_id": "temperature-comparison-alternate",
        }
    )
    second_result = detect_conflicts(
        first_binding.candidates,
        second_contract,
        first_binding.comparison_request,
        ConflictDetectionConfig(maximum_candidates=16),
    )
    second_binding = ConflictBinding(
        comparison_contract=second_contract,
        comparison_request=first_binding.comparison_request,
        candidates=first_binding.candidates,
        result=second_result,
    )

    data["conflict_bindings"] = (
        first_binding,
        second_binding,
    )
    authoritative = AuthoritativeMethodInput(**data)
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    result = methods._current_multi_stream_support(
        configuration,
        authoritative,
    )

    assert isinstance(result, AuthoritativeAnalyticalSet)
    assert result.support_observation_ids == (
        UUID(int=1),
        UUID(int=2),
    )
    assert all(
        item.role == "USED"
        for item in result.evidence_use
    )

    reversed_data = dict(data)
    reversed_data["conflict_bindings"] = tuple(
        reversed(data["conflict_bindings"])
    )
    reversed_authoritative = AuthoritativeMethodInput(
        **reversed_data
    )

    reversed_result = methods._current_multi_stream_support(
        configuration,
        reversed_authoritative,
    )

    assert reversed_result == result


def test_r2b_current_multi_stream_separate_agreement_groups_are_never_merged():
    records = (
        r2_observation(
            1,
            -10,
            source_instance="uuid:GPU-A",
            value=50,
        ),
        r2_observation(
            2,
            -10,
            source_instance="uuid:GPU-B",
            value=50,
        ),
        r2_observation(
            3,
            -10,
            source_instance="uuid:GPU-C",
            value=50,
        ),
        r2_observation(
            4,
            -10,
            source_instance="uuid:GPU-D",
            value=50,
        ),
    )

    data = r2_bundle_data(
        records=records,
        include_conflict=False,
        page_size=4,
    )
    identities = data["identities"]
    field = data["field_contract"]

    first_binding = r2_conflict_binding(
        records[:2],
        identities,
        field,
    )
    second_binding = r2_conflict_binding(
        records[2:],
        identities,
        field,
    )

    data["conflict_bindings"] = (
        first_binding,
        second_binding,
    )

    authoritative = AuthoritativeMethodInput(**data)
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    result = methods._current_multi_stream_support(
        configuration,
        authoritative,
    )

    assert isinstance(result, MethodNoResult)
    assert (
        result.reason
        == MethodNoResultReason.NO_SINGLE_COMPARABLE_ANALYTICAL_SET
    )
    assert tuple(
        item.observation_id
        for item in result.evidence_use
    ) == (
        UUID(int=1),
        UUID(int=2),
        UUID(int=3),
        UUID(int=4),
    )
    assert all(
        item.role == "EXCLUDED"
        for item in result.evidence_use
    )
    assert {
        item.reason
        for item in result.evidence_use
    } == {
        "method:no_single_comparable_analytical_set",
    }

    reversed_data = dict(data)
    reversed_data["conflict_bindings"] = tuple(
        reversed(data["conflict_bindings"])
    )
    reversed_authoritative = AuthoritativeMethodInput(
        **reversed_data
    )

    reversed_result = methods._current_multi_stream_support(
        configuration,
        reversed_authoritative,
    )

    assert reversed_result == result


def test_r2b_current_full_unresolved_identity_conflict_blocks_full_agreement():
    records = (
        r2_observation(
            1,
            -10,
            source_instance="uuid:GPU-A",
            value=50,
        ),
        r2_observation(
            2,
            -10,
            source_instance="uuid:GPU-B",
            value=50,
        ),
    )

    data = r2_bundle_data(
        records=records,
        include_conflict=True,
        page_size=2,
    )

    agreement_binding = data["conflict_bindings"][0]
    assert len(agreement_binding.result.agreements) == 1
    assert not agreement_binding.result.conflicts

    conflict_request = ComparisonRequest(
        affected_field_key=agreement_binding.comparison_request.affected_field_key,
        quantity_id=agreement_binding.comparison_request.quantity_id,
        expected_identity={
            "subject_id": data["field_contract"].subject_scope,
            "workload_id": "intentionally-unmatched-workload",
        },
    )

    conflict_result = detect_conflicts(
        agreement_binding.candidates,
        agreement_binding.comparison_contract,
        conflict_request,
        ConflictDetectionConfig(maximum_candidates=16),
    )

    assert len(conflict_result.conflicts) == 1
    assert (
        conflict_result.conflicts[0].kind.value
        == "IDENTITY_MISMATCH"
    )
    assert not conflict_result.agreements

    conflict_binding = ConflictBinding(
        comparison_contract=agreement_binding.comparison_contract,
        comparison_request=conflict_request,
        candidates=agreement_binding.candidates,
        result=conflict_result,
    )

    data["conflict_bindings"] = (
        agreement_binding,
        conflict_binding,
    )

    authoritative = AuthoritativeMethodInput(**data)
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    result = methods._current_multi_stream_support(
        configuration,
        authoritative,
    )

    assert isinstance(result, MethodNoResult)
    assert result.reason == MethodNoResultReason.UNRESOLVED_CONFLICT
    assert tuple(
        item.observation_id
        for item in result.evidence_use
    ) == (
        UUID(int=1),
        UUID(int=2),
    )
    assert all(
        item.role == "EXCLUDED"
        for item in result.evidence_use
    )
    assert all(
        item.reason.startswith(
            "conflict:IDENTITY_MISMATCH:"
        )
        for item in result.evidence_use
    )

    reversed_data = dict(data)
    reversed_data["conflict_bindings"] = tuple(
        reversed(data["conflict_bindings"])
    )
    reversed_authoritative = AuthoritativeMethodInput(
        **reversed_data
    )

    reversed_result = methods._current_multi_stream_support(
        configuration,
        reversed_authoritative,
    )

    assert reversed_result == result


def test_r2b_current_distinct_scopes_with_same_conflict_reason_remain_unresolved():
    data = r2_agreement_data(
        first_value=50,
        second_value=50,
    )
    agreement_binding = data["conflict_bindings"][0]

    first_conflict_request = ComparisonRequest(
        affected_field_key=agreement_binding.comparison_request.affected_field_key,
        quantity_id=agreement_binding.comparison_request.quantity_id,
        expected_identity={
            "subject_id": data["field_contract"].subject_scope,
            "workload_id": "unmatched-workload-a",
        },
    )
    second_conflict_request = ComparisonRequest(
        affected_field_key=agreement_binding.comparison_request.affected_field_key,
        quantity_id=agreement_binding.comparison_request.quantity_id,
        expected_identity={
            "subject_id": data["field_contract"].subject_scope,
            "workload_id": "unmatched-workload-b",
        },
    )

    first_conflict_result = detect_conflicts(
        agreement_binding.candidates,
        agreement_binding.comparison_contract,
        first_conflict_request,
        ConflictDetectionConfig(maximum_candidates=16),
    )
    second_conflict_result = detect_conflicts(
        agreement_binding.candidates,
        agreement_binding.comparison_contract,
        second_conflict_request,
        ConflictDetectionConfig(maximum_candidates=16),
    )

    assert first_conflict_result.conflicts
    assert second_conflict_result.conflicts
    assert (
        first_conflict_result.conflicts[0].kind.value
        == "IDENTITY_MISMATCH"
    )
    assert (
        second_conflict_result.conflicts[0].kind.value
        == "IDENTITY_MISMATCH"
    )

    first_conflict_binding = ConflictBinding(
        comparison_contract=agreement_binding.comparison_contract,
        comparison_request=first_conflict_request,
        candidates=agreement_binding.candidates,
        result=first_conflict_result,
    )
    second_conflict_binding = ConflictBinding(
        comparison_contract=agreement_binding.comparison_contract,
        comparison_request=second_conflict_request,
        candidates=agreement_binding.candidates,
        result=second_conflict_result,
    )

    data["conflict_bindings"] = (
        agreement_binding,
        first_conflict_binding,
        second_conflict_binding,
    )

    authoritative = AuthoritativeMethodInput(**data)
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    result = methods._current_multi_stream_support(
        configuration,
        authoritative,
    )

    assert isinstance(result, MethodNoResult)
    assert result.reason == MethodNoResultReason.UNRESOLVED_CONFLICT
    assert all(
        item.role == "EXCLUDED"
        for item in result.evidence_use
    )
    assert all(
        item.reason.startswith(
            "conflict:IDENTITY_MISMATCH:"
        )
        for item in result.evidence_use
    )

    reversed_data = dict(data)
    reversed_data["conflict_bindings"] = tuple(
        reversed(data["conflict_bindings"])
    )
    reversed_authoritative = AuthoritativeMethodInput(
        **reversed_data
    )

    reversed_result = methods._current_multi_stream_support(
        configuration,
        reversed_authoritative,
    )

    assert reversed_result == result


def test_r2b_current_multiple_full_unresolved_conflicts_remain_unresolved():
    field = field_contract(
        maximum_alignment_seconds=1,
    )
    records = (
        r2_observation(
            1,
            -10,
            source_instance="uuid:GPU-A",
            value=50,
        ),
        r2_observation(
            2,
            -5,
            source_instance="uuid:GPU-B",
            value=50,
        ),
    )

    data = r2_bundle_data(
        records=records,
        contract=field,
        include_conflict=False,
        page_size=2,
    )

    identities = data["identities"]

    temporal_binding = r2_conflict_binding(
        records,
        identities,
        field,
    )

    assert len(temporal_binding.result.conflicts) == 1
    assert (
        temporal_binding.result.conflicts[0].kind.value
        == "TEMPORAL_MISALIGNMENT"
    )

    identity_request = ComparisonRequest(
        affected_field_key=(
            temporal_binding
            .comparison_request
            .affected_field_key
        ),
        quantity_id=(
            temporal_binding
            .comparison_request
            .quantity_id
        ),
        expected_identity={
            "subject_id": field.subject_scope,
            "workload_id": "intentionally-unmatched-workload",
        },
    )

    identity_result = detect_conflicts(
        temporal_binding.candidates,
        temporal_binding.comparison_contract,
        identity_request,
        ConflictDetectionConfig(maximum_candidates=16),
    )

    assert len(identity_result.conflicts) == 1
    assert (
        identity_result.conflicts[0].kind.value
        == "IDENTITY_MISMATCH"
    )

    identity_binding = ConflictBinding(
        comparison_contract=(
            temporal_binding.comparison_contract
        ),
        comparison_request=identity_request,
        candidates=temporal_binding.candidates,
        result=identity_result,
    )

    data["conflict_bindings"] = (
        temporal_binding,
        identity_binding,
    )

    authoritative = AuthoritativeMethodInput(**data)
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    result = methods._current_multi_stream_support(
        configuration,
        authoritative,
    )

    assert isinstance(result, MethodNoResult)
    assert (
        result.reason
        == MethodNoResultReason.UNRESOLVED_CONFLICT
    )

    assert tuple(
        item.observation_id
        for item in result.evidence_use
    ) == (
        UUID(int=1),
        UUID(int=2),
    )

    assert all(
        item.role == "EXCLUDED"
        for item in result.evidence_use
    )

    temporal_conflict = temporal_binding.result.conflicts[0]
    identity_conflict = identity_binding.result.conflicts[0]

    accepted_artifact_reasons = {
        (
            "conflict:"
            f"{temporal_conflict.kind.value}:"
            f"{temporal_conflict.reason}"
        ),
        (
            "conflict:"
            f"{identity_conflict.kind.value}:"
            f"{identity_conflict.reason}"
        ),
    }

    assert all(
        item.reason in accepted_artifact_reasons
        for item in result.evidence_use
    )

    assert all(
        item.reason
        != "method:no_single_comparable_analytical_set"
        for item in result.evidence_use
    )

    reversed_data = dict(data)
    reversed_data["conflict_bindings"] = tuple(
        reversed(data["conflict_bindings"])
    )

    reversed_authoritative = AuthoritativeMethodInput(
        **reversed_data
    )

    reversed_result = methods._current_multi_stream_support(
        configuration,
        reversed_authoritative,
    )

    assert reversed_result == result


def test_r2b_current_not_compared_never_authorizes_cross_stream_join():
    records = (
        r2_observation(
            1,
            -10,
            source_instance="uuid:GPU-A",
            value=50,
        ),
        r2_observation(
            2,
            -10,
            source_instance="uuid:GPU-B",
            value=None,
        ),
    )
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=records,
            include_conflict=True,
        )
    )
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    dispositions = methods._conflict_binding_dispositions(
        authoritative.conflict_bindings[0]
    )
    assert all(
        disposition[0] == "NOT_COMPARED"
        for disposition in dispositions.values()
    )

    assert (
        methods._current_multi_stream_support(
            configuration,
            authoritative,
        )
        is None
    )

    surviving = methods._current_single_stream_support(
        configuration,
        authoritative,
    )

    assert isinstance(surviving, AuthoritativeAnalyticalSet)
    assert surviving.support_observation_ids == (UUID(int=1),)
    assert tuple(
        item.observation_id
        for item in surviving.evidence_use
    ) == (
        UUID(int=1),
        UUID(int=2),
    )
    assert tuple(
        item.role
        for item in surviving.evidence_use
    ) == (
        "USED",
        "EXCLUDED",
    )


def test_r2b_current_multi_stream_support_leaves_single_stream_to_b3a():
    authoritative = r2_bundle()
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    assert (
        methods._current_multi_stream_support(
            configuration,
            authoritative,
        )
        is None
    )


def test_r2b_current_single_stream_support_builds_closed_analytical_set():
    authoritative = r2_bundle()
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    result = methods._current_single_stream_support(
        configuration,
        authoritative,
    )

    assert isinstance(result, AuthoritativeAnalyticalSet)
    assert result.support_view == "CURRENT"
    assert result.support_observation_ids == (
        UUID(int=1),
        UUID(int=2),
    )
    assert tuple(
        item.observation_id
        for item in result.evidence_use
        if item.role == "USED"
    ) == result.support_observation_ids
    assert {
        item.reason
        for item in result.evidence_use
        if item.role == "USED"
    } == {"authoritative_single_stream_support"}


def test_r2b_historical_support_binding_builds_same_segment_set():
    records = (
        r2_observation(2, -20, value=40),
        r2_observation(1, -10, value=50),
    )
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(records=records)
    )
    configuration = build_method_configuration(
        method_name="within_segment_delta",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    result = methods._historical_support_binding(
        configuration,
        authoritative,
    )

    assert isinstance(result, AuthoritativeAnalyticalSet)
    assert result.support_view == "HISTORICAL"
    assert result.support_observation_ids == (
        UUID(int=2),
        UUID(int=1),
    )
    assert result.continuity_segment_id == (
        authoritative.continuity_result.segments[0].segment_id
    )
    assert tuple(
        item.observation_id
        for item in result.evidence_use
        if item.role == "USED"
    ) == result.support_observation_ids
    assert {
        item.reason
        for item in result.evidence_use
        if item.role == "USED"
    } == {
        "authoritative_same_segment_historical_support"
    }


def test_r2b_historical_support_binding_returns_honest_empty_no_result():
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(records=())
    )
    configuration = build_method_configuration(
        method_name="historical_endpoint_slope",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    result = methods._historical_support_binding(
        configuration,
        authoritative,
    )

    assert isinstance(result, MethodNoResult)
    assert (
        result.reason
        == MethodNoResultReason.NO_ELIGIBLE_HISTORICAL_EVIDENCE
    )
    assert result.evidence_use == ()


def test_r2b_historical_support_binding_refuses_cross_segment_population():
    contract = field_contract(
        maximum_gap_seconds=5,
    )
    records = (
        r2_observation(1, -20, value=10),
        r2_observation(2, -10, value=20),
    )
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=records,
            contract=contract,
        )
    )
    configuration = build_method_configuration(
        method_name="within_segment_delta",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    assert len(authoritative.continuity_result.segments) == 2

    result = methods._historical_support_binding(
        configuration,
        authoritative,
    )

    assert isinstance(result, MethodNoResult)
    assert (
        result.reason
        == MethodNoResultReason.NO_SINGLE_CONTINUITY_SEGMENT
    )
    assert all(
        item.role == "EXCLUDED"
        for item in result.evidence_use
    )
    assert {
        item.reason
        for item in result.evidence_use
    } == {
        "method:no_single_continuity_segment"
    }


def test_r2b_historical_support_binding_refuses_insufficient_segment():
    contract = field_contract(
        minimum_samples=3,
    )
    records = (
        r2_observation(1, -20, value=10),
        r2_observation(2, -10, value=20),
    )
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=records,
            contract=contract,
        )
    )
    configuration = build_method_configuration(
        method_name="historical_endpoint_slope",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    assert len(authoritative.continuity_result.segments) == 1
    assert not (
        authoritative.continuity_result
        .segments[0]
        .evidence_sufficient_for_derivation
    )

    result = methods._historical_support_binding(
        configuration,
        authoritative,
    )

    assert isinstance(result, MethodNoResult)
    assert (
        result.reason
        == MethodNoResultReason.NO_SINGLE_CONTINUITY_SEGMENT
    )
    assert {
        item.reason
        for item in result.evidence_use
    } == {
        "method:no_single_continuity_segment"
    }


def test_r2b_historical_support_binding_uses_stale_context_as_history():
    contract = field_contract(
        admissible_quality=(
            Quality.VALID,
            Quality.STALE,
        ),
    )
    records = (
        r2_observation(
            1,
            -20,
            value=40,
            quality=Quality.STALE,
        ),
        r2_observation(
            2,
            -10,
            value=50,
        ),
    )
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=records,
            contract=contract,
        )
    )
    configuration = build_method_configuration(
        method_name="source_time_counter_rate",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    stale_admission = authoritative.admission_map[UUID(int=1)]

    assert not stale_admission.eligible_for_current
    assert stale_admission.eligible_for_history

    result = methods._historical_support_binding(
        configuration,
        authoritative,
    )

    assert isinstance(result, AuthoritativeAnalyticalSet)
    assert result.support_view == "HISTORICAL"
    assert result.support_observation_ids == (
        UUID(int=1),
        UUID(int=2),
    )


def test_r2b_historical_multi_stream_without_authority_has_no_hidden_winner():
    records = (
        r2_observation(
            1,
            -10,
            source_instance="uuid:GPU-A",
            value=50,
        ),
        r2_observation(
            2,
            -10,
            source_instance="uuid:GPU-B",
            value=50,
        ),
    )
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=records,
            include_conflict=False,
            page_size=2,
        )
    )
    configuration = build_method_configuration(
        method_name="within_segment_delta",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    result = methods._historical_support_binding(
        configuration,
        authoritative,
    )

    assert isinstance(result, MethodNoResult)
    assert (
        result.reason
        == MethodNoResultReason.NO_SINGLE_COMPARABLE_ANALYTICAL_SET
    )
    assert all(
        item.role == "EXCLUDED"
        for item in result.evidence_use
    )
    assert {
        item.reason
        for item in result.evidence_use
    } == {
        "method:no_single_comparable_analytical_set"
    }


def test_r2b_historical_full_agreement_still_requires_one_continuity_segment():
    records = (
        r2_observation(
            1,
            -10,
            source_instance="uuid:GPU-A",
            value=50,
        ),
        r2_observation(
            2,
            -10,
            source_instance="uuid:GPU-B",
            value=50,
        ),
    )
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=records,
            include_conflict=True,
            page_size=2,
        )
    )
    configuration = build_method_configuration(
        method_name="historical_endpoint_slope",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    assert authoritative.conflict_bindings
    assert authoritative.conflict_bindings[0].result.agreements

    result = methods._historical_support_binding(
        configuration,
        authoritative,
    )

    assert isinstance(result, MethodNoResult)
    assert (
        result.reason
        == MethodNoResultReason.NO_SINGLE_CONTINUITY_SEGMENT
    )
    assert {
        item.reason
        for item in result.evidence_use
    } == {
        "method:no_single_continuity_segment"
    }


def test_r2b_historical_full_conflict_blocks_support_before_continuity():
    records = (
        r2_observation(
            1,
            -10,
            source_instance="uuid:GPU-A",
            value=50,
        ),
        r2_observation(
            2,
            -10,
            source_instance="uuid:GPU-B",
            value=55,
        ),
    )
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=records,
            include_conflict=True,
            page_size=2,
        )
    )
    configuration = build_method_configuration(
        method_name="within_segment_delta",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    assert authoritative.conflict_bindings
    assert authoritative.conflict_bindings[0].result.conflicts

    result = methods._historical_support_binding(
        configuration,
        authoritative,
    )

    assert isinstance(result, MethodNoResult)
    assert result.reason == MethodNoResultReason.UNRESOLVED_CONFLICT
    assert all(
        item.role == "EXCLUDED"
        for item in result.evidence_use
    )
    assert all(
        item.reason.startswith("conflict:")
        for item in result.evidence_use
    )


def test_r2b_current_single_stream_support_remains_independent_of_not_compared():
    record = r2_observation(1, -10)
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=(record,),
            include_conflict=True,
        )
    )
    configuration = build_method_configuration(
        method_name="latest_eligible_value",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    disposition = methods._conflict_binding_dispositions(
        authoritative.conflict_bindings[0]
    )
    assert disposition[record.observation_id][0] == "NOT_COMPARED"

    result = methods._current_single_stream_support(
        configuration,
        authoritative,
    )

    assert isinstance(result, AuthoritativeAnalyticalSet)
    assert result.support_observation_ids == (
        record.observation_id,
    )


def test_r2b_current_single_stream_support_returns_honest_empty_no_result():
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(records=())
    )
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    result = methods._current_single_stream_support(
        configuration,
        authoritative,
    )

    assert isinstance(result, MethodNoResult)
    assert (
        result.reason
        == MethodNoResultReason.NO_ELIGIBLE_CURRENT_EVIDENCE
    )
    assert result.evidence_use == ()


def test_r2b_current_single_stream_support_preserves_exclusion_provenance():
    unresolved = r2_observation(
        1,
        -10,
        provenance={},
    )
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(records=(unresolved,))
    )
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    result = methods._current_single_stream_support(
        configuration,
        authoritative,
    )

    assert isinstance(result, MethodNoResult)
    assert (
        result.reason
        == MethodNoResultReason.NO_ELIGIBLE_CURRENT_EVIDENCE
    )
    assert len(result.evidence_use) == 1
    assert result.evidence_use[0].role == "EXCLUDED"
    assert result.evidence_use[0].reason.startswith(
        "identity:subject:"
    )


def test_r2b_current_single_stream_helper_does_not_invent_cross_stream_authority():
    records = (
        r2_observation(
            1,
            -20,
            source_instance="uuid:GPU-A",
        ),
        r2_observation(
            2,
            -10,
            source_instance="uuid:GPU-B",
        ),
    )
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(records=records)
    )
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    assert (
        methods._current_single_stream_support(
            configuration,
            authoritative,
        )
        is None
    )


def test_r2b_current_single_stream_support_canonically_orders_used_and_excluded():
    records = (
        r2_observation(
            1,
            -20,
            provenance={},
        ),
        r2_observation(
            2,
            -10,
        ),
    )
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(records=records)
    )
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    result = methods._current_single_stream_support(
        configuration,
        authoritative,
    )

    assert isinstance(result, AuthoritativeAnalyticalSet)
    assert result.support_observation_ids == (UUID(int=2),)
    assert tuple(
        item.observation_id
        for item in result.evidence_use
    ) == (
        UUID(int=1),
        UUID(int=2),
    )
    assert tuple(
        item.role
        for item in result.evidence_use
    ) == (
        "EXCLUDED",
        "USED",
    )


def test_r2b_public_bind_method_support_dispatches_current():
    authoritative = r2_bundle()
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    public_result = methods.bind_method_support(
        configuration=configuration,
        authoritative_input=authoritative,
    )
    private_result = methods._current_single_stream_support(
        configuration,
        authoritative,
    )

    assert public_result == private_result
    assert isinstance(
        public_result,
        AuthoritativeAnalyticalSet,
    )
    assert public_result.support_view == "CURRENT"


def test_r2b_public_bind_method_support_dispatches_current_multi_stream():
    authoritative = AuthoritativeMethodInput(
        **r2_agreement_data(
            first_value=50,
            second_value=50,
        )
    )
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    public_result = methods.bind_method_support(
        configuration=configuration,
        authoritative_input=authoritative,
    )
    private_result = methods._current_multi_stream_support(
        configuration,
        authoritative,
    )

    assert public_result == private_result
    assert isinstance(
        public_result,
        AuthoritativeAnalyticalSet,
    )


def test_r2b_public_bind_method_support_dispatches_historical():
    records = (
        r2_observation(2, -20, value=40),
        r2_observation(1, -10, value=50),
    )
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(records=records)
    )
    configuration = build_method_configuration(
        method_name="within_segment_delta",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    public_result = methods.bind_method_support(
        configuration=configuration,
        authoritative_input=authoritative,
    )
    private_result = methods._historical_support_binding(
        configuration,
        authoritative,
    )

    assert public_result == private_result
    assert isinstance(
        public_result,
        AuthoritativeAnalyticalSet,
    )
    assert public_result.support_view == "HISTORICAL"


def test_r2b_public_bind_method_support_returns_missing_opportunity_no_result():
    authoritative = r2_bundle()
    configuration = build_method_configuration(
        method_name="missing_fraction",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    result = methods.bind_method_support(
        configuration=configuration,
        authoritative_input=authoritative,
    )

    assert isinstance(result, MethodNoResult)
    assert (
        result.reason
        == MethodNoResultReason.MISSING_OPPORTUNITY_AUTHORITY
    )
    assert tuple(
        item.observation_id
        for item in result.evidence_use
    ) == tuple(
        observation.observation_id
        for observation in methods._canonical_considered_observations(
            authoritative
        )
    )
    assert all(
        item.role == "EXCLUDED"
        for item in result.evidence_use
    )
    assert {
        item.reason
        for item in result.evidence_use
    } == {
        "method:missing_opportunity_authority"
    }


def test_r2b_public_bind_method_support_missing_opportunity_empty_population():
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(records=())
    )
    configuration = build_method_configuration(
        method_name="missing_fraction",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    result = methods.bind_method_support(
        configuration=configuration,
        authoritative_input=authoritative,
    )

    assert isinstance(result, MethodNoResult)
    assert (
        result.reason
        == MethodNoResultReason.MISSING_OPPORTUNITY_AUTHORITY
    )
    assert result.evidence_use == ()


def test_r2b_public_bind_method_support_validates_field_contract_binding():
    authoritative = r2_bundle()
    other_contract = field_contract(
        contract_id="different-contract",
    )
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=other_contract,
    )

    with pytest.raises(FieldContractBindingError):
        methods.bind_method_support(
            configuration=configuration,
            authoritative_input=authoritative,
        )


def test_r2b_public_bind_method_support_is_keyword_only():
    authoritative = r2_bundle()
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    with pytest.raises(TypeError):
        methods.bind_method_support(
            configuration,
            authoritative,
        )


def test_r2b_public_binder_never_exposes_method_value_execution():
    authoritative = r2_bundle()
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    result = methods.bind_method_support(
        configuration=configuration,
        authoritative_input=authoritative,
    )

    assert not isinstance(result, MethodValueResult)
    assert not hasattr(methods, "compute_method")


def test_r2b_contract_surface_is_narrow_and_execution_remains_absent():
    for symbol in (
        "ConflictBinding",
        "AuthoritativeMethodInput",
        "AuthoritativeAnalyticalSet",
    ):
        assert symbol in methods.__all__
        assert hasattr(methods, symbol)

    assert "bind_method_support" in methods.__all__
    assert hasattr(methods, "bind_method_support")

    for symbol in (
        "compute_method",
        "MethodExecutionLimits",
    ):
        assert not hasattr(methods, symbol)


def test_r2c_public_binder_rejects_forged_configuration_digest():
    authoritative = r2_bundle()
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    forged = configuration.model_copy()
    object.__setattr__(
        forged,
        "configuration_sha256",
        "0" * 64,
    )

    with pytest.raises(InvalidMethodConfigurationError):
        methods.bind_method_support(
            configuration=forged,
            authoritative_input=authoritative,
        )


def test_r2c_public_binder_rejects_forged_method_version():
    authoritative = r2_bundle()
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    forged = configuration.model_copy()
    payload = forged.semantic_payload.model_copy()

    object.__setattr__(
        payload,
        "method_version",
        "v999",
    )
    object.__setattr__(
        forged,
        "semantic_payload",
        payload,
    )

    with pytest.raises(InvalidMethodConfigurationError):
        methods.bind_method_support(
            configuration=forged,
            authoritative_input=authoritative,
        )


def test_r2c_public_binder_rejects_forged_authoritative_input_without_raw_keyerror():
    authoritative = r2_bundle()
    configuration = build_method_configuration(
        method_name="arithmetic_mean",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    forged = authoritative.model_copy()
    object.__setattr__(
        forged,
        "admissions",
        forged.admissions[:-1],
    )

    with pytest.raises(MethodError) as exc_info:
        methods.bind_method_support(
            configuration=configuration,
            authoritative_input=forged,
        )

    assert not isinstance(exc_info.value, KeyError)


@pytest.mark.parametrize(
    "method_name",
    tuple(method.value for method in MethodName),
)
def test_r2c_all_nine_method_identities_reach_closed_public_dispatch(
    method_name: str,
):
    if method_name in {
        "within_segment_delta",
        "source_time_counter_rate",
        "historical_endpoint_slope",
    }:
        authoritative = AuthoritativeMethodInput(
            **r2_bundle_data(
                records=(
                    r2_observation(2, -20, value=40),
                    r2_observation(1, -10, value=50),
                )
            )
        )
    else:
        authoritative = r2_bundle()

    configuration = build_method_configuration(
        method_name=method_name,
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    result = methods.bind_method_support(
        configuration=configuration,
        authoritative_input=authoritative,
    )

    assert isinstance(
        result,
        (AuthoritativeAnalyticalSet, MethodNoResult),
    )
    assert not isinstance(result, MethodValueResult)


def test_r2c_public_execution_surface_remains_non_arithmetic():
    assert "bind_method_support" in methods.__all__
    assert hasattr(methods, "bind_method_support")

    assert "compute_method" not in methods.__all__
    assert not hasattr(methods, "compute_method")

    assert "MethodExecutionLimits" not in methods.__all__
    assert not hasattr(methods, "MethodExecutionLimits")


# ---------------------------------------------------------------------------
# S4A-R3 ? latest + exact current aggregates
# ---------------------------------------------------------------------------


def r3_execute_for_test(
    method_name: MethodName | str,
    records: tuple[RuntimeObservation, ...],
    *,
    contract: FieldEvidenceContract | None = None,
):
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=records,
            contract=contract,
        )
    )
    configuration = build_method_configuration(
        method_name=method_name,
        method_version="v1",
        field_contract=authoritative.field_contract,
    )
    result = methods._execute_r3_method(
        configuration=configuration,
        authoritative_input=authoritative,
    )
    return result


def r3_result_context():
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=(
                r2_observation(
                    1,
                    -10,
                    value=5,
                ),
            )
        )
    )
    configuration = build_method_configuration(
        method_name="latest_eligible_value",
        method_version="v1",
        field_contract=authoritative.field_contract,
    )
    bound = methods.bind_method_support(
        configuration=configuration,
        authoritative_input=authoritative,
    )
    assert isinstance(
        bound,
        methods.AuthoritativeAnalyticalSet,
    )
    unit_semantics = MethodUnitSemantics(
        kind="FIELD_VALUE",
        value_unit=authoritative.field_contract.output_unit,
        declared_result_unit=authoritative.field_contract.output_unit,
    )
    return configuration, bound, unit_semantics


def test_r3_result_envelope_preserves_strict_scalar_kinds():
    configuration, bound, unit_semantics = r3_result_context()

    values = (
        (5, int),
        (0.5, float),
        (-0.0, float),
        ("stable", str),
        (True, bool),
    )

    for value, expected_type in values:
        result = MethodValueResult(
            configuration=configuration,
            value=value,
            unit_semantics=unit_semantics,
            evidence_use=bound.evidence_use,
        )
        assert type(result.value) is expected_type

    negative_zero = MethodValueResult(
        configuration=configuration,
        value=-0.0,
        unit_semantics=unit_semantics,
        evidence_use=bound.evidence_use,
    )

    assert isinstance(negative_zero.value, float)
    assert math.copysign(1.0, negative_zero.value) == -1.0


@pytest.mark.parametrize(
    "value",
    (
        float("nan"),
        float("inf"),
        float("-inf"),
    ),
)
def test_r3_result_envelope_rejects_nonfinite_raw_floats(value: float):
    configuration, bound, unit_semantics = r3_result_context()

    with pytest.raises(ValidationError):
        MethodValueResult(
            configuration=configuration,
            value=value,
            unit_semantics=unit_semantics,
            evidence_use=bound.evidence_use,
        )


def test_r3_latest_preserves_integer_scalar():
    result = r3_execute_for_test(
        MethodName.LATEST_ELIGIBLE_VALUE,
        (
            r2_observation(
                1,
                -5,
                value=2**53 + 1,
            ),
        ),
    )

    assert isinstance(result, MethodValueResult)
    assert type(result.value) is int
    assert result.value == 2**53 + 1


def test_r3_latest_preserves_finite_float_scalar():
    result = r3_execute_for_test(
        MethodName.LATEST_ELIGIBLE_VALUE,
        (
            r2_observation(
                1,
                -5,
                value=0.1,
            ),
        ),
    )

    assert isinstance(result, MethodValueResult)
    assert type(result.value) is float
    assert result.value == 0.1


def test_r3_latest_preserves_negative_signed_zero():
    result = r3_execute_for_test(
        MethodName.LATEST_ELIGIBLE_VALUE,
        (
            r2_observation(
                1,
                -5,
                value=-0.0,
            ),
        ),
    )

    assert isinstance(result, MethodValueResult)
    assert type(result.value) is float
    assert result.value == 0.0
    assert math.copysign(1.0, result.value) == -1.0


def test_r3_latest_preserves_string_scalar():
    result = r3_execute_for_test(
        MethodName.LATEST_ELIGIBLE_VALUE,
        (
            r2_observation(
                1,
                -5,
                value="stable",
            ),
        ),
    )

    assert isinstance(result, MethodValueResult)
    assert type(result.value) is str
    assert result.value == "stable"


def test_r3_latest_preserves_boolean_scalar():
    result = r3_execute_for_test(
        MethodName.LATEST_ELIGIBLE_VALUE,
        (
            r2_observation(
                1,
                -5,
                value=True,
            ),
        ),
    )

    assert isinstance(result, MethodValueResult)
    assert type(result.value) is bool
    assert result.value is True


def test_r3_latest_uses_source_observation_time_only():
    records = (
        r2_observation(
            1,
            -20,
            value=100,
            ingestion_time=R2_T - timedelta(seconds=1),
        ),
        r2_observation(
            2,
            -5,
            value=1,
            ingestion_time=R2_T - timedelta(seconds=4),
        ),
    )

    result = r3_execute_for_test(
        MethodName.LATEST_ELIGIBLE_VALUE,
        records,
    )

    assert isinstance(result, MethodValueResult)
    assert result.value == 1

    used = tuple(
        item.observation_id
        for item in result.evidence_use
        if item.role == "USED"
    )
    assert used == (UUID(int=2),)


def test_r3_latest_uses_guardian_receipt_time_only():
    contract = field_contract(
        contract_id="r3-receipt-time",
        temporal_basis=TimeBasis.GUARDIAN_RECEIPT_TIME,
    )

    records = (
        r2_observation(
            1,
            -10,
            value=100,
            ingestion_time=R2_T - timedelta(seconds=1),
        ),
        r2_observation(
            2,
            -10,
            value=1,
            ingestion_time=R2_T - timedelta(seconds=5),
        ),
    )

    result = r3_execute_for_test(
        MethodName.LATEST_ELIGIBLE_VALUE,
        records,
        contract=contract,
    )

    assert isinstance(result, MethodValueResult)
    assert result.value == 100

    used = tuple(
        item.observation_id
        for item in result.evidence_use
        if item.role == "USED"
    )
    assert used == (UUID(int=1),)


def test_r3_latest_equal_selected_time_returns_ambiguity():
    records = (
        r2_observation(
            1,
            -5,
            value=10,
            ingestion_time=R2_T - timedelta(seconds=4),
        ),
        r2_observation(
            2,
            -5,
            value=20,
            ingestion_time=R2_T - timedelta(seconds=1),
        ),
    )

    result = r3_execute_for_test(
        MethodName.LATEST_ELIGIBLE_VALUE,
        records,
    )

    assert isinstance(result, MethodNoResult)
    assert (
        result.reason
        == MethodNoResultReason.AMBIGUOUS_LATEST_TIME
    )
    assert all(
        item.role == "EXCLUDED"
        for item in result.evidence_use
    )

    assert {
        item.reason
        for item in result.evidence_use
    } == {
        "method:ambiguous_latest_time"
    }


def test_r3_latest_accounts_for_earlier_support_without_discarding_it_upstream():
    records = (
        r2_observation(
            1,
            -20,
            value=100,
        ),
        r2_observation(
            2,
            -5,
            value=1,
        ),
    )

    result = r3_execute_for_test(
        MethodName.LATEST_ELIGIBLE_VALUE,
        records,
    )

    assert isinstance(result, MethodValueResult)

    accounting = {
        item.observation_id: (
            item.role,
            item.reason,
        )
        for item in result.evidence_use
    }

    assert accounting[UUID(int=2)][0] == "USED"

    assert accounting[UUID(int=1)] == (
        "EXCLUDED",
        "method:not_latest_chronological_point",
    )


def test_r3_latest_is_invariant_to_caller_record_permutation():
    records = (
        r2_observation(
            1,
            -20,
            value=100,
        ),
        r2_observation(
            2,
            -10,
            value=50,
        ),
        r2_observation(
            3,
            -5,
            value=25,
        ),
    )

    first = r3_execute_for_test(
        MethodName.LATEST_ELIGIBLE_VALUE,
        records,
    )

    second = r3_execute_for_test(
        MethodName.LATEST_ELIGIBLE_VALUE,
        tuple(reversed(records)),
    )

    assert first == second


@pytest.mark.parametrize(
    "value",
    (
        [1, 2],
        {"value": 1},
    ),
)
def test_r3_latest_rejects_non_scalar_value_kinds(value):
    with pytest.raises(UnsupportedValueKindError):
        r3_execute_for_test(
            MethodName.LATEST_ELIGIBLE_VALUE,
            (
                r2_observation(
                    1,
                    -5,
                    value=value,
                ),
            ),
        )


def test_r3_latest_none_propagates_authoritative_binder_no_result():
    observation = r2_observation(
        1,
        -5,
        value=None,
    )

    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=(observation,),
        )
    )

    configuration = build_method_configuration(
        method_name=MethodName.LATEST_ELIGIBLE_VALUE,
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    bound = methods.bind_method_support(
        configuration=configuration,
        authoritative_input=authoritative,
    )

    executed = methods._execute_r3_method(
        configuration=configuration,
        authoritative_input=authoritative,
    )

    assert isinstance(bound, MethodNoResult)
    assert executed == bound


def test_r3_mean_of_integers_is_exact():
    result = r3_execute_for_test(
        MethodName.ARITHMETIC_MEAN,
        (
            r2_observation(
                1,
                -20,
                value=1,
            ),
            r2_observation(
                2,
                -10,
                value=2,
            ),
            r2_observation(
                3,
                -5,
                value=3,
            ),
        ),
    )

    assert isinstance(result, MethodValueResult)
    assert result.value == ExactNumber(
        numerator=2,
        denominator=1,
    )


def test_r3_mean_preserves_large_integer_exactness():
    result = r3_execute_for_test(
        MethodName.ARITHMETIC_MEAN,
        (
            r2_observation(
                1,
                -20,
                value=2**53 + 1,
            ),
            r2_observation(
                2,
                -5,
                value=2**53 + 3,
            ),
        ),
    )

    assert isinstance(result, MethodValueResult)
    assert result.value == ExactNumber(
        numerator=2**53 + 2,
        denominator=1,
    )


def test_r3_mean_uses_exact_binary_float_ratio():
    result = r3_execute_for_test(
        MethodName.ARITHMETIC_MEAN,
        (
            r2_observation(
                1,
                -5,
                value=0.1,
            ),
        ),
    )

    assert isinstance(result, MethodValueResult)
    assert result.value == ExactNumber.from_value(0.1)


def test_r3_mean_is_exact_under_extreme_cancellation_and_permutation():
    records = (
        r2_observation(
            1,
            -20,
            value=10**100,
        ),
        r2_observation(
            2,
            -10,
            value=-10**100,
        ),
        r2_observation(
            3,
            -5,
            value=3,
        ),
    )

    first = r3_execute_for_test(
        MethodName.ARITHMETIC_MEAN,
        records,
    )

    second = r3_execute_for_test(
        MethodName.ARITHMETIC_MEAN,
        tuple(reversed(records)),
    )

    assert first == second
    assert isinstance(first, MethodValueResult)
    assert first.value == ExactNumber(
        numerator=1,
        denominator=1,
    )


def test_r3_mean_arithmetic_zero_is_canonical_positive_zero():
    result = r3_execute_for_test(
        MethodName.ARITHMETIC_MEAN,
        (
            r2_observation(
                1,
                -10,
                value=-1,
            ),
            r2_observation(
                2,
                -5,
                value=1,
            ),
        ),
    )

    assert isinstance(result, MethodValueResult)
    assert result.value == ExactNumber(
        numerator=0,
        denominator=1,
    )


def test_r3_median_odd_cardinality_is_exact():
    result = r3_execute_for_test(
        MethodName.MEDIAN,
        (
            r2_observation(
                1,
                -20,
                value=9,
            ),
            r2_observation(
                2,
                -10,
                value=1,
            ),
            r2_observation(
                3,
                -5,
                value=4,
            ),
        ),
    )

    assert isinstance(result, MethodValueResult)
    assert result.value == ExactNumber(
        numerator=4,
        denominator=1,
    )


def test_r3_median_even_cardinality_uses_exact_midpoint():
    result = r3_execute_for_test(
        MethodName.MEDIAN,
        (
            r2_observation(
                1,
                -25,
                value=1,
            ),
            r2_observation(
                2,
                -20,
                value=2,
            ),
            r2_observation(
                3,
                -10,
                value=3,
            ),
            r2_observation(
                4,
                -5,
                value=4,
            ),
        ),
    )

    assert isinstance(result, MethodValueResult)
    assert result.value == ExactNumber(
        numerator=5,
        denominator=2,
    )


def test_r3_median_preserves_duplicate_numeric_values():
    result = r3_execute_for_test(
        MethodName.MEDIAN,
        (
            r2_observation(
                1,
                -25,
                value=1,
            ),
            r2_observation(
                2,
                -20,
                value=2,
            ),
            r2_observation(
                3,
                -10,
                value=2,
            ),
            r2_observation(
                4,
                -5,
                value=3,
            ),
        ),
    )

    assert isinstance(result, MethodValueResult)
    assert result.value == ExactNumber(
        numerator=2,
        denominator=1,
    )


def test_r3_min_handles_negative_values_exactly():
    result = r3_execute_for_test(
        MethodName.MIN,
        (
            r2_observation(
                1,
                -20,
                value=-2,
            ),
            r2_observation(
                2,
                -10,
                value=-100,
            ),
            r2_observation(
                3,
                -5,
                value=4,
            ),
        ),
    )

    assert isinstance(result, MethodValueResult)
    assert result.value == ExactNumber(
        numerator=-100,
        denominator=1,
    )


def test_r3_max_handles_negative_only_values_exactly():
    result = r3_execute_for_test(
        MethodName.MAX,
        (
            r2_observation(
                1,
                -20,
                value=-9,
            ),
            r2_observation(
                2,
                -10,
                value=-2,
            ),
            r2_observation(
                3,
                -5,
                value=-5,
            ),
        ),
    )

    assert isinstance(result, MethodValueResult)
    assert result.value == ExactNumber(
        numerator=-2,
        denominator=1,
    )


@pytest.mark.parametrize(
    ("method_name", "expected"),
    (
        (
            MethodName.MIN,
            ExactNumber(
                numerator=2**80 + 1,
                denominator=1,
            ),
        ),
        (
            MethodName.MAX,
            ExactNumber(
                numerator=2**80 + 9,
                denominator=1,
            ),
        ),
    ),
)
def test_r3_min_max_preserve_very_large_integers(
    method_name: MethodName,
    expected: ExactNumber,
):
    result = r3_execute_for_test(
        method_name,
        (
            r2_observation(
                1,
                -20,
                value=2**80 + 9,
            ),
            r2_observation(
                2,
                -5,
                value=2**80 + 1,
            ),
        ),
    )

    assert isinstance(result, MethodValueResult)
    assert result.value == expected


@pytest.mark.parametrize(
    ("method_name", "expected"),
    (
        (
            MethodName.MIN,
            ExactNumber(
                numerator=1,
                denominator=1,
            ),
        ),
        (
            MethodName.MAX,
            ExactNumber(
                numerator=9,
                denominator=1,
            ),
        ),
    ),
)
def test_r3_min_max_keep_complete_support_accounting_for_ties(
    method_name: MethodName,
    expected: ExactNumber,
):
    result = r3_execute_for_test(
        method_name,
        (
            r2_observation(
                1,
                -20,
                value=1,
            ),
            r2_observation(
                2,
                -15,
                value=1,
            ),
            r2_observation(
                3,
                -10,
                value=9,
            ),
            r2_observation(
                4,
                -5,
                value=9,
            ),
        ),
    )

    assert isinstance(result, MethodValueResult)
    assert result.value == expected

    used_ids = {
        item.observation_id
        for item in result.evidence_use
        if item.role == "USED"
    }

    assert used_ids == {
        UUID(int=1),
        UUID(int=2),
        UUID(int=3),
        UUID(int=4),
    }


@pytest.mark.parametrize(
    "method_name",
    (
        MethodName.ARITHMETIC_MEAN,
        MethodName.MEDIAN,
        MethodName.MIN,
        MethodName.MAX,
    ),
)
@pytest.mark.parametrize(
    "value",
    (
        True,
        "42",
    ),
)
def test_r3_numeric_aggregates_reject_non_numeric_support(
    method_name: MethodName,
    value,
):
    with pytest.raises(UnsupportedValueKindError):
        r3_execute_for_test(
            method_name,
            (
                r2_observation(
                    1,
                    -5,
                    value=value,
                ),
            ),
        )


@pytest.mark.parametrize(
    "method_name",
    (
        MethodName.ARITHMETIC_MEAN,
        MethodName.MEDIAN,
        MethodName.MIN,
        MethodName.MAX,
    ),
)
def test_r3_aggregate_results_are_exact_numbers(
    method_name: MethodName,
):
    result = r3_execute_for_test(
        method_name,
        (
            r2_observation(
                1,
                -10,
                value=1,
            ),
            r2_observation(
                2,
                -5,
                value=3,
            ),
        ),
    )

    assert isinstance(result, MethodValueResult)
    assert isinstance(result.value, ExactNumber)


def test_r3_propagates_binder_no_result_unchanged():
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=(),
        )
    )
    configuration = build_method_configuration(
        method_name=MethodName.ARITHMETIC_MEAN,
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    bound = methods.bind_method_support(
        configuration=configuration,
        authoritative_input=authoritative,
    )

    executed = methods._execute_r3_method(
        configuration=configuration,
        authoritative_input=authoritative,
    )

    assert isinstance(bound, MethodNoResult)
    assert executed == bound


def test_r3_missing_result_unit_is_an_ordinary_no_result():
    contract = field_contract(
        contract_id="r3-no-output-unit",
        output_unit=None,
    )

    result = r3_execute_for_test(
        MethodName.ARITHMETIC_MEAN,
        (
            r2_observation(
                1,
                -5,
                value=5,
            ),
        ),
        contract=contract,
    )

    assert isinstance(result, MethodNoResult)

    assert (
        result.reason
        == MethodNoResultReason.RESULT_UNIT_SEMANTICS_UNDECLARED
    )

    assert all(
        item.role == "EXCLUDED"
        for item in result.evidence_use
    )

    assert {
        item.reason
        for item in result.evidence_use
    } == {
        "method:result_unit_semantics_undeclared"
    }


def test_r3_does_not_execute_a_declared_unit_conversion():
    contract = field_contract(
        contract_id="r3-no-conversion",
        allowed_units=(
            "degC",
            "degF",
        ),
        allowed_conversions=(
            "fahrenheit_to_celsius_v1",
        ),
    )

    observation = r2_observation(
        1,
        -5,
        value=86,
        unit="degF",
    )

    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=(observation,),
            contract=contract,
        )
    )

    configuration = build_method_configuration(
        method_name=MethodName.ARITHMETIC_MEAN,
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    bound = methods.bind_method_support(
        configuration=configuration,
        authoritative_input=authoritative,
    )

    executed = methods._execute_r3_method(
        configuration=configuration,
        authoritative_input=authoritative,
    )

    assert isinstance(bound, MethodNoResult)
    assert executed == bound
    assert any(
        item.reason == "unit_conversion_not_authorized"
        for item in bound.evidence_use
    )


def test_r3_private_execution_surface_does_not_accept_caller_support():
    authoritative = r2_bundle()

    configuration = build_method_configuration(
        method_name=MethodName.ARITHMETIC_MEAN,
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    bound = methods.bind_method_support(
        configuration=configuration,
        authoritative_input=authoritative,
    )

    assert isinstance(
        bound,
        methods.AuthoritativeAnalyticalSet,
    )

    assert tuple(
        signature(methods._execute_r3_method).parameters
    ) == (
        "configuration",
        "authoritative_input",
    )

    with pytest.raises(TypeError):
        methods._execute_r3_method(
            configuration=configuration,
            authoritative_input=authoritative,
            analytical_set=bound,
        )


@pytest.mark.parametrize(
    "method_name",
    (
        MethodName.LATEST_ELIGIBLE_VALUE,
        MethodName.ARITHMETIC_MEAN,
        MethodName.MEDIAN,
        MethodName.MIN,
        MethodName.MAX,
    ),
)
def test_r3_repeated_execution_is_deterministic(
    method_name: MethodName,
):
    records = (
        r2_observation(
            1,
            -20,
            value=1,
        ),
        r2_observation(
            2,
            -10,
            value=3,
        ),
        r2_observation(
            3,
            -5,
            value=5,
        ),
    )

    first = r3_execute_for_test(
        method_name,
        records,
    )

    second = r3_execute_for_test(
        method_name,
        records,
    )

    assert first == second


def test_r3_recognized_r4_method_is_not_misreported_as_unknown():
    authoritative = r2_bundle()

    configuration = build_method_configuration(
        method_name=MethodName.WITHIN_SEGMENT_DELTA,
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    with pytest.raises(MethodOperationError) as exc_info:
        methods._execute_r3_method(
            configuration=configuration,
            authoritative_input=authoritative,
        )

    assert not isinstance(
        exc_info.value,
        UnknownMethodError,
    )


def test_r3_public_compute_method_remains_absent():
    assert "_execute_r3_method" not in methods.__all__
    assert "compute_method" not in methods.__all__
    assert not hasattr(methods, "compute_method")
    assert not hasattr(methods, "MethodExecutionLimits")


# ---------------------------------------------------------------------------
# S4A-R4 ? delta / source-time counter rate / historical endpoint slope
# ---------------------------------------------------------------------------


def r4_execute_for_test(
    method_name: MethodName | str,
    records: tuple[
        RuntimeObservation,
        ...,
    ],
    *,
    contract: FieldEvidenceContract | None = None,
):
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=records,
            contract=contract,
        )
    )

    configuration = build_method_configuration(
        method_name=method_name,
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    return methods._execute_r4_method(
        configuration=configuration,
        authoritative_input=authoritative,
    )


def test_r4_delta_uses_authoritative_endpoints_exactly():
    result = r4_execute_for_test(
        MethodName.WITHIN_SEGMENT_DELTA,
        (
            r2_observation(
                1,
                -20,
                value=10,
            ),
            r2_observation(
                2,
                -10,
                value=25,
            ),
        ),
    )

    assert isinstance(
        result,
        MethodValueResult,
    )

    assert result.value == ExactNumber(
        numerator=15,
        denominator=1,
    )

    assert (
        result.unit_semantics.kind
        == "FIELD_VALUE"
    )


def test_r4_delta_preserves_negative_direction():
    result = r4_execute_for_test(
        MethodName.WITHIN_SEGMENT_DELTA,
        (
            r2_observation(
                1,
                -20,
                value=50,
            ),
            r2_observation(
                2,
                -10,
                value=20,
            ),
        ),
    )

    assert isinstance(
        result,
        MethodValueResult,
    )

    assert result.value == ExactNumber(
        numerator=-30,
        denominator=1,
    )


def test_r4_delta_preserves_large_integer_exactness():
    result = r4_execute_for_test(
        MethodName.WITHIN_SEGMENT_DELTA,
        (
            r2_observation(
                1,
                -20,
                value=2**80 + 1,
            ),
            r2_observation(
                2,
                -10,
                value=2**80 + 9,
            ),
        ),
    )

    assert isinstance(
        result,
        MethodValueResult,
    )

    assert result.value == ExactNumber(
        numerator=8,
        denominator=1,
    )


def test_r4_delta_keeps_intermediate_support_used():
    result = r4_execute_for_test(
        MethodName.WITHIN_SEGMENT_DELTA,
        (
            r2_observation(
                1,
                -25,
                value=10,
            ),
            r2_observation(
                2,
                -20,
                value=999,
            ),
            r2_observation(
                3,
                -10,
                value=40,
            ),
        ),
    )

    assert isinstance(
        result,
        MethodValueResult,
    )

    assert result.value == ExactNumber(
        numerator=30,
        denominator=1,
    )

    used_ids = tuple(
        item.observation_id
        for item in result.evidence_use
        if item.role == "USED"
    )

    assert used_ids == (
        UUID(int=1),
        UUID(int=2),
        UUID(int=3),
    )


def test_r4_delta_is_invariant_to_caller_record_permutation():
    records = (
        r2_observation(
            1,
            -25,
            value=10,
        ),
        r2_observation(
            2,
            -20,
            value=20,
        ),
        r2_observation(
            3,
            -10,
            value=40,
        ),
    )

    first = r4_execute_for_test(
        MethodName.WITHIN_SEGMENT_DELTA,
        records,
    )

    second = r4_execute_for_test(
        MethodName.WITHIN_SEGMENT_DELTA,
        tuple(reversed(records)),
    )

    assert first == second


def test_r4_source_time_rate_uses_source_clock_not_receipt_clock():
    contract = field_contract(
        contract_id="r4-source-rate-clock",
        temporal_basis=(
            TimeBasis.GUARDIAN_RECEIPT_TIME
        ),
    )

    records = (
        r2_observation(
            1,
            -20,
            value=40,
            ingestion_time=(
                R2_T
                - timedelta(seconds=8)
            ),
        ),
        r2_observation(
            2,
            -10,
            value=50,
            ingestion_time=(
                R2_T
                - timedelta(seconds=3)
            ),
        ),
    )

    result = r4_execute_for_test(
        MethodName.SOURCE_TIME_COUNTER_RATE,
        records,
        contract=contract,
    )

    assert isinstance(
        result,
        MethodValueResult,
    )

    assert result.value == ExactNumber(
        numerator=1,
        denominator=1,
    )

    assert (
        result.unit_semantics.kind
        == "COUNTER_QUANTITY_PER_SOURCE_TIME"
    )

    assert (
        result.unit_semantics.denominator_time_basis
        == "SOURCE_TIME"
    )

    assert (
        result.unit_semantics.numerator_unit
        == contract.output_unit
    )

    assert (
        result.unit_semantics.declared_result_unit
        is None
    )


def test_r4_source_time_rate_preserves_exact_large_integer_delta():
    result = r4_execute_for_test(
        MethodName.SOURCE_TIME_COUNTER_RATE,
        (
            r2_observation(
                1,
                -13,
                value=2**53 + 1,
            ),
            r2_observation(
                2,
                -10,
                value=2**53 + 4,
            ),
        ),
    )

    assert isinstance(
        result,
        MethodValueResult,
    )

    assert result.value == ExactNumber(
        numerator=1,
        denominator=1,
    )


def test_r4_source_time_rate_refuses_nonpositive_source_interval():
    contract = field_contract(
        contract_id="r4-zero-source-rate",
        temporal_basis=(
            TimeBasis.GUARDIAN_RECEIPT_TIME
        ),
    )

    shared_source_time = (
        R2_T
        - timedelta(seconds=20)
    )

    records = (
        r2_observation(
            1,
            -20,
            value=40,
            observation_time=shared_source_time,
            ingestion_time=(
                R2_T
                - timedelta(seconds=15)
            ),
            processing_time=(
                R2_T
                - timedelta(seconds=15)
            ),
        ),
        r2_observation(
            2,
            -20,
            value=50,
            observation_time=shared_source_time,
            ingestion_time=(
                R2_T
                - timedelta(seconds=10)
            ),
            processing_time=(
                R2_T
                - timedelta(seconds=10)
            ),
        ),
    )

    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=records,
            contract=contract,
        )
    )

    configuration = build_method_configuration(
        method_name=(
            MethodName.SOURCE_TIME_COUNTER_RATE
        ),
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    bound = methods.bind_method_support(
        configuration=configuration,
        authoritative_input=authoritative,
    )

    assert isinstance(
        bound,
        AuthoritativeAnalyticalSet,
    )

    assert (
        bound.support_view
        == "HISTORICAL"
    )

    assert (
        bound.support_observation_ids
        == (
            UUID(int=1),
            UUID(int=2),
        )
    )

    first = (
        authoritative
        .observations_by_id[
            bound.support_observation_ids[0]
        ]
    )

    last = (
        authoritative
        .observations_by_id[
            bound.support_observation_ids[-1]
        ]
    )

    assert (
        first.observation_time
        == last.observation_time
    )

    assert (
        first.ingestion_time
        < last.ingestion_time
    )

    result = methods._execute_r4_method(
        configuration=configuration,
        authoritative_input=authoritative,
    )

    assert isinstance(
        result,
        MethodNoResult,
    )

    assert (
        result.reason
        == MethodNoResultReason.NO_POSITIVE_ELAPSED_INTERVAL
    )

    assert all(
        item.role == "EXCLUDED"
        for item in result.evidence_use
    )

    assert {
        item.reason
        for item in result.evidence_use
    } == {
        "method:no_positive_elapsed_interval"
    }


def test_r4_historical_slope_uses_source_basis_when_configured():
    contract = field_contract(
        contract_id="r4-slope-source",
        temporal_basis=(
            TimeBasis.SOURCE_OBSERVATION_TIME
        ),
    )

    result = r4_execute_for_test(
        MethodName.HISTORICAL_ENDPOINT_SLOPE,
        (
            r2_observation(
                1,
                -20,
                value=40,
                ingestion_time=(
                    R2_T
                    - timedelta(seconds=8)
                ),
            ),
            r2_observation(
                2,
                -10,
                value=50,
                ingestion_time=(
                    R2_T
                    - timedelta(seconds=3)
                ),
            ),
        ),
        contract=contract,
    )

    assert isinstance(
        result,
        MethodValueResult,
    )

    assert result.value == ExactNumber(
        numerator=1,
        denominator=1,
    )

    assert (
        result.unit_semantics.kind
        == "VALUE_QUANTITY_PER_HISTORICAL_TIME"
    )

    assert (
        result.unit_semantics.denominator_time_basis
        == "HISTORICAL_TIME"
    )


def test_r4_historical_slope_uses_receipt_basis_when_configured():
    contract = field_contract(
        contract_id="r4-slope-receipt",
        temporal_basis=(
            TimeBasis.GUARDIAN_RECEIPT_TIME
        ),
    )

    result = r4_execute_for_test(
        MethodName.HISTORICAL_ENDPOINT_SLOPE,
        (
            r2_observation(
                1,
                -20,
                value=40,
                ingestion_time=(
                    R2_T
                    - timedelta(seconds=8)
                ),
            ),
            r2_observation(
                2,
                -10,
                value=50,
                ingestion_time=(
                    R2_T
                    - timedelta(seconds=3)
                ),
            ),
        ),
        contract=contract,
    )

    assert isinstance(
        result,
        MethodValueResult,
    )

    assert result.value == ExactNumber(
        numerator=2,
        denominator=1,
    )


@pytest.mark.parametrize(
    "method_name",
    (
        MethodName.WITHIN_SEGMENT_DELTA,
        MethodName.SOURCE_TIME_COUNTER_RATE,
        MethodName.HISTORICAL_ENDPOINT_SLOPE,
    ),
)
def test_r4_methods_return_undeclared_unit_no_result(
    method_name: MethodName,
):
    contract = field_contract(
        contract_id=(
            "r4-no-output-unit-"
            f"{method_name.value}"
        ),
        output_unit=None,
    )

    result = r4_execute_for_test(
        method_name,
        (
            r2_observation(
                1,
                -20,
                value=10,
            ),
            r2_observation(
                2,
                -10,
                value=20,
            ),
        ),
        contract=contract,
    )

    assert isinstance(
        result,
        MethodNoResult,
    )

    assert (
        result.reason
        == MethodNoResultReason.RESULT_UNIT_SEMANTICS_UNDECLARED
    )

    assert all(
        item.role == "EXCLUDED"
        for item in result.evidence_use
    )

    assert {
        item.reason
        for item in result.evidence_use
    } == {
        "method:result_unit_semantics_undeclared"
    }


@pytest.mark.parametrize(
    "method_name",
    (
        MethodName.WITHIN_SEGMENT_DELTA,
        MethodName.SOURCE_TIME_COUNTER_RATE,
        MethodName.HISTORICAL_ENDPOINT_SLOPE,
    ),
)
def test_r4_methods_require_two_bound_support_observations(
    method_name: MethodName,
):
    contract = field_contract(
        contract_id=(
            "r4-cardinality-"
            f"{method_name.value}"
        ),
        minimum_samples=1,
    )

    result = r4_execute_for_test(
        method_name,
        (
            r2_observation(
                1,
                -10,
                value=10,
            ),
        ),
        contract=contract,
    )

    assert isinstance(
        result,
        MethodNoResult,
    )

    assert (
        result.reason
        == MethodNoResultReason.INSUFFICIENT_CARDINALITY
    )

    assert all(
        item.role == "EXCLUDED"
        for item in result.evidence_use
    )

    assert {
        item.reason
        for item in result.evidence_use
    } == {
        "method:insufficient_cardinality"
    }


@pytest.mark.parametrize(
    "method_name",
    (
        MethodName.WITHIN_SEGMENT_DELTA,
        MethodName.SOURCE_TIME_COUNTER_RATE,
        MethodName.HISTORICAL_ENDPOINT_SLOPE,
    ),
)
def test_r4_methods_reject_boolean_arithmetic(
    method_name: MethodName,
):
    with pytest.raises(
        UnsupportedValueKindError
    ):
        r4_execute_for_test(
            method_name,
            (
                r2_observation(
                    1,
                    -20,
                    value=False,
                ),
                r2_observation(
                    2,
                    -10,
                    value=True,
                ),
            ),
        )


@pytest.mark.parametrize(
    "method_name",
    (
        MethodName.WITHIN_SEGMENT_DELTA,
        MethodName.SOURCE_TIME_COUNTER_RATE,
        MethodName.HISTORICAL_ENDPOINT_SLOPE,
    ),
)
def test_r4_methods_propagate_binder_no_result_unchanged(
    method_name: MethodName,
):
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=(),
        )
    )

    configuration = build_method_configuration(
        method_name=method_name,
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    bound = methods.bind_method_support(
        configuration=configuration,
        authoritative_input=authoritative,
    )

    executed = methods._execute_r4_method(
        configuration=configuration,
        authoritative_input=authoritative,
    )

    assert isinstance(
        bound,
        MethodNoResult,
    )

    assert executed == bound


def test_r4_private_execution_surface_does_not_accept_caller_support():
    authoritative = AuthoritativeMethodInput(
        **r2_bundle_data(
            records=(
                r2_observation(
                    1,
                    -20,
                    value=10,
                ),
                r2_observation(
                    2,
                    -10,
                    value=20,
                ),
            ),
        )
    )

    configuration = build_method_configuration(
        method_name=(
            MethodName.WITHIN_SEGMENT_DELTA
        ),
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    bound = methods.bind_method_support(
        configuration=configuration,
        authoritative_input=authoritative,
    )

    assert isinstance(
        bound,
        AuthoritativeAnalyticalSet,
    )

    assert tuple(
        signature(
            methods._execute_r4_method
        ).parameters
    ) == (
        "configuration",
        "authoritative_input",
    )

    with pytest.raises(TypeError):
        methods._execute_r4_method(
            configuration=configuration,
            authoritative_input=authoritative,
            analytical_set=bound,
        )


@pytest.mark.parametrize(
    "method_name",
    (
        MethodName.WITHIN_SEGMENT_DELTA,
        MethodName.SOURCE_TIME_COUNTER_RATE,
        MethodName.HISTORICAL_ENDPOINT_SLOPE,
    ),
)
def test_r4_repeated_execution_is_deterministic(
    method_name: MethodName,
):
    records = (
        r2_observation(
            1,
            -20,
            value=10,
        ),
        r2_observation(
            2,
            -10,
            value=20,
        ),
    )

    first = r4_execute_for_test(
        method_name,
        records,
    )

    second = r4_execute_for_test(
        method_name,
        records,
    )

    assert first == second


def test_r4_recognized_r3_method_is_not_misreported_as_unknown():
    authoritative = r2_bundle()

    configuration = build_method_configuration(
        method_name=(
            MethodName.ARITHMETIC_MEAN
        ),
        method_version="v1",
        field_contract=authoritative.field_contract,
    )

    with pytest.raises(
        MethodOperationError
    ) as exc_info:
        methods._execute_r4_method(
            configuration=configuration,
            authoritative_input=authoritative,
        )

    assert not isinstance(
        exc_info.value,
        UnknownMethodError,
    )


def test_r4_public_compute_method_remains_absent():
    assert (
        "_execute_r4_method"
        not in methods.__all__
    )

    assert (
        "compute_method"
        not in methods.__all__
    )

    assert not hasattr(
        methods,
        "compute_method",
    )


def test_r4_r3_private_surface_remains_present_and_private():
    assert hasattr(
        methods,
        "_execute_r3_method",
    )

    assert (
        "_execute_r3_method"
        not in methods.__all__
    )
