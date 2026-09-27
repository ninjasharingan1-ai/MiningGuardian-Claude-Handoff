"""Immutable foundations and authoritative input binding for M3.2 state methods.

R1 owns method/configuration identity, exact numeric identity, narrow method
outcomes, and the stable exception hierarchy. R2-A adds only detached structural
binding of accepted S2/S3 artifacts. There is no estimator dispatch, analytical
set selection, or method arithmetic in this module.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timedelta
from enum import StrEnum
from fractions import Fraction
from math import gcd
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from mining_guardian.observability.models import RuntimeObservation
from mining_guardian.state.admission import (
    ADMISSION_METHOD,
    ADMISSION_METHOD_VERSION,
    AdmissionAssessment,
)
from mining_guardian.state.conflicts import (
    CONFLICT_METHOD,
    CONFLICT_METHOD_VERSION,
    ComparableEvidence,
    ComparisonContract,
    ComparisonRequest,
    ConflictDetectionResult,
)
from mining_guardian.state.continuity import (
    CONTINUITY_METHOD,
    CONTINUITY_METHOD_VERSION,
    AnalyticalSegment,
    BreakReason,
    ContinuityContract,
    ContinuityResult,
)
from mining_guardian.state.contracts import (
    ConflictKind,
    ConflictResolutionStatus,
    FieldEvidenceContract,
    FieldRequest,
    Name,
    StateContract,
    TimeBasis,
)
from mining_guardian.state.evidence_query import (
    AssociationMode,
    EvidenceQueryRequest,
    EvidenceQueryResult,
    QueryCompleteness,
    QueryIntegrity,
)
from mining_guardian.state.subjects import (
    SUBJECT_RESOLUTION_METHOD,
    SUBJECT_RESOLUTION_METHOD_VERSION,
    IdentityComponentStatus,
    IdentityResolution,
    deterministic_digest,
    deterministic_uuid,
)

__all__ = (
    "AuthoritativeAnalyticalSet",
    "AuthoritativeMethodInput",
    "ConflictBinding",
    "ContinuityViolationError",
    "DeterministicArithmeticError",
    "DuplicateObservationIdentityError",
    "ExactNumber",
    "FieldContractBindingError",
    "InvalidMethodConfigurationError",
    "MalformedAuthoritativeInputError",
    "MalformedS3ArtifactError",
    "MethodConfiguration",
    "MethodConfigurationSemanticPayload",
    "MethodConstructionError",
    "MethodError",
    "MethodEvidenceUse",
    "MethodName",
    "MethodNoResult",
    "MethodNoResultReason",
    "MethodOperationError",
    "MethodOutcome",
    "MethodResourceLimitError",
    "MethodUnitSemantics",
    "MethodValueResult",
    "MethodVersion",
    "UnknownMethodError",
    "UnsupportedMethodVersionError",
    "UnsupportedValueKindError",
    "bind_method_support",
    "build_method_configuration",
    "method_configuration_digest",
    "supported_method_versions",
)

_METHOD_CONFIGURATION_SCHEMA_VERSION: Literal["m3.2.method-configuration.v1"] = (
    "m3.2.method-configuration.v1"
)

_LowerSha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class MethodError(Exception):
    """Base class for deterministic-method failures."""


class MethodConstructionError(MethodError):
    """A method foundation could not be constructed faithfully."""


class InvalidMethodConfigurationError(MethodConstructionError):
    """Serialized or constructed method configuration is invalid."""


class MalformedAuthoritativeInputError(MethodConstructionError):
    """A future authoritative method-input wrapper is malformed."""


class DuplicateObservationIdentityError(MethodConstructionError):
    """One authoritative input repeats an observation identity."""


class MethodOperationError(MethodError):
    """A deterministic method operation cannot be performed."""


class UnknownMethodError(MethodOperationError):
    """The requested method identity is not supported."""


class UnsupportedMethodVersionError(MethodOperationError):
    """The requested explicit method version is not supported."""


class FieldContractBindingError(MethodOperationError):
    """Method configuration and field-contract identity do not agree."""


class MalformedS3ArtifactError(MethodOperationError):
    """A future authoritative S3 artifact is structurally inconsistent."""


class UnsupportedValueKindError(MethodOperationError):
    """A method received a value kind outside its frozen domain."""


class ContinuityViolationError(MethodOperationError):
    """A method operation would cross an authoritative continuity boundary."""


class MethodResourceLimitError(MethodOperationError):
    """A bounded method operation exceeded its explicit resource limit."""


class DeterministicArithmeticError(MethodOperationError):
    """Exact deterministic arithmetic could not produce an authorized result."""


class MethodName(StrEnum):
    """The exact frozen generic method identities; aliases are not accepted."""

    LATEST_ELIGIBLE_VALUE = "latest_eligible_value"
    ARITHMETIC_MEAN = "arithmetic_mean"
    MEDIAN = "median"
    MIN = "min"
    MAX = "max"
    WITHIN_SEGMENT_DELTA = "within_segment_delta"
    SOURCE_TIME_COUNTER_RATE = "source_time_counter_rate"
    HISTORICAL_ENDPOINT_SLOPE = "historical_endpoint_slope"
    MISSING_FRACTION = "missing_fraction"


class MethodVersion(StrEnum):
    """Explicit method versions.  No implicit latest-version alias exists."""

    V1 = "v1"


type _MethodSupportView = Literal["CURRENT", "HISTORICAL"]


_CURRENT_SUPPORT_METHODS = frozenset(
    {
        MethodName.LATEST_ELIGIBLE_VALUE,
        MethodName.ARITHMETIC_MEAN,
        MethodName.MEDIAN,
        MethodName.MIN,
        MethodName.MAX,
    }
)

_HISTORICAL_SUPPORT_METHODS = frozenset(
    {
        MethodName.WITHIN_SEGMENT_DELTA,
        MethodName.SOURCE_TIME_COUNTER_RATE,
        MethodName.HISTORICAL_ENDPOINT_SLOPE,
    }
)


def _support_view_for_method(method_name: MethodName) -> _MethodSupportView | None:
    if method_name in _CURRENT_SUPPORT_METHODS:
        return "CURRENT"
    if method_name in _HISTORICAL_SUPPORT_METHODS:
        return "HISTORICAL"
    if method_name == MethodName.MISSING_FRACTION:
        return None
    raise UnknownMethodError(f"unsupported method identity: {method_name!r}")


_SUPPORTED_METHOD_VERSIONS: Mapping[MethodName, frozenset[MethodVersion]] = MappingProxyType(
    {method_name: frozenset({MethodVersion.V1}) for method_name in MethodName}
)


def supported_method_versions() -> Mapping[MethodName, frozenset[MethodVersion]]:
    """Return the immutable closed method/version inventory."""

    return _SUPPORTED_METHOD_VERSIONS


class _InvariantStateContract(StateContract):
    """Keep every public R1 construction path inside Pydantic validation."""

    model_config = ConfigDict(revalidate_instances="always")

    def copy(self, *args: Any, **kwargs: Any) -> Self:
        """Disable Pydantic's deprecated, non-validating copy API."""

        del args, kwargs
        raise TypeError(
            f"{type(self).__name__}.copy() is disabled; use model_copy() for validated copies"
        )

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Return a validated copy, including validation of nested model instances."""

        values = self.model_dump(mode="python", round_trip=True)
        if update:
            values.update(update)
        if deep:
            values = deepcopy(values)
        return type(self).model_validate(values)

    @classmethod
    def model_construct(cls, _fields_set: set[str] | None = None, **values: Any) -> Self:
        """Disable Pydantic's intentionally non-validating construction API."""

        del _fields_set, values
        raise TypeError(f"{cls.__name__}.model_construct() is disabled; use validated construction")


class _DefensiveSnapshotStateContract(_InvariantStateContract):
    """Keep canonical R2-A authority private and return detached field snapshots."""

    def __getattribute__(self, name: str) -> Any:
        canonical = object.__getattribute__(self, "__dict__")
        if name == "__dict__":
            return deepcopy(canonical)
        model_type = object.__getattribute__(self, "__class__")
        if name in model_type.model_fields and name in canonical:
            return deepcopy(canonical[name])
        return super().__getattribute__(name)

    def __copy__(self) -> Self:
        return self.model_copy(deep=True)

    def __deepcopy__(self, memo: dict[int, Any] | None = None) -> Self:
        del memo
        return self.model_copy(deep=True)


class _SerializedConfigurationContract(_InvariantStateContract):
    """Reserve raw configuration ingestion for the duplicate-aware envelope parser."""

    @model_validator(mode="before")
    @classmethod
    def reject_pydantic_json_mode(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> object:
        """Keep all Pydantic JSON-mode ingestion behind the duplicate-aware parser."""

        if info.mode == "json":
            raise ValueError(
                "raw JSON configuration input is disabled; "
                "use MethodConfiguration.from_serialized()"
            )
        return value

    @classmethod
    def model_validate_json(cls, *args: Any, **kwargs: Any) -> Self:
        del args, kwargs
        raise TypeError(
            f"{cls.__name__}.model_validate_json() is disabled; "
            "use MethodConfiguration.from_serialized() for raw serialized configuration input"
        )

    @classmethod
    def parse_raw(cls, *args: Any, **kwargs: Any) -> Self:
        del args, kwargs
        raise TypeError(
            f"{cls.__name__}.parse_raw() is disabled; "
            "use MethodConfiguration.from_serialized() for raw serialized configuration input"
        )

    @classmethod
    def parse_file(cls, *args: Any, **kwargs: Any) -> Self:
        del args, kwargs
        raise TypeError(
            f"{cls.__name__}.parse_file() is disabled; "
            "use MethodConfiguration.from_serialized() for raw serialized configuration input"
        )


class ExactNumber(_InvariantStateContract):
    """Canonical exact rational identity for observed values and method results."""

    numerator: int
    denominator: int = 1

    @model_validator(mode="before")
    @classmethod
    def canonical_ratio(cls, value: object) -> object:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("ExactNumber requires a numerator and optional denominator")

        values = dict(value)
        unknown_fields = values.keys() - {"numerator", "denominator"}
        if unknown_fields:
            names = ", ".join(sorted(unknown_fields))
            raise ValueError(f"unexpected ExactNumber field(s): {names}")
        if "numerator" not in values:
            raise ValueError("ExactNumber requires a numerator")
        numerator = values.get("numerator")
        denominator = values.get("denominator", 1)

        if isinstance(numerator, bool) or isinstance(denominator, bool):
            raise ValueError("bool is not an exact numeric value")
        if not isinstance(denominator, int):
            raise ValueError("ExactNumber denominator must be an integer")
        if denominator == 0:
            raise ValueError("ExactNumber denominator must be nonzero")

        if isinstance(numerator, float):
            if denominator != 1:
                raise ValueError("a float ExactNumber cannot also supply a rational denominator")
            if not math.isfinite(numerator):
                raise ValueError("ExactNumber requires a finite numeric value")
            numerator, denominator = numerator.as_integer_ratio()
        elif not isinstance(numerator, int):
            raise ValueError("ExactNumber numerator must be an int or finite float")

        if denominator < 0:
            numerator = -numerator
            denominator = -denominator
        if numerator == 0:
            return {"numerator": 0, "denominator": 1}

        common = gcd(abs(numerator), denominator)
        return {"numerator": numerator // common, "denominator": denominator // common}

    @classmethod
    def from_value(cls, value: int | float) -> Self:
        """Construct from an exact integer or a finite float's binary ratio."""

        return cls.model_validate({"numerator": value})

    @classmethod
    def from_ratio(cls, numerator: int, denominator: int) -> Self:
        """Construct a normalized exact rational value."""

        return cls(numerator=numerator, denominator=denominator)


class MethodConfigurationSemanticPayload(_SerializedConfigurationContract):
    """The exact, non-self-referential method-configuration digest preimage."""

    schema_version: Literal["m3.2.method-configuration.v1"]
    method_name: MethodName
    method_version: MethodVersion
    field_contract_id: Name
    field_contract_version: Name
    semantic_parameters: tuple[()]

    @field_validator("semantic_parameters", mode="before")
    @classmethod
    def parameters_are_explicitly_empty(cls, value: object) -> tuple[()]:
        if not isinstance(value, (tuple, list)) or len(value) != 0:
            raise ValueError("semantic_parameters must be an explicit empty collection")
        return ()

    @model_validator(mode="after")
    def method_version_is_supported(self) -> Self:
        if self.method_version not in _SUPPORTED_METHOD_VERSIONS[self.method_name]:
            raise ValueError("unsupported method/version identity")
        return self

    def canonical_json_bytes(self) -> bytes:
        """Serialize this semantic payload to its deterministic UTF-8 JSON form."""

        actual_state = dict(self.__dict__)
        validated = type(self).model_validate(actual_state)
        for field_name in type(self).model_fields:
            actual_value = actual_state[field_name]
            validated_value = getattr(validated, field_name)
            if type(actual_value) is not type(validated_value) or actual_value != validated_value:
                raise ValueError("semantic payload must already be in validated canonical state")
        payload: dict[str, object] = {
            "schema_version": validated.schema_version,
            "method_name": validated.method_name.value,
            "method_version": validated.method_version.value,
            "field_contract_id": validated.field_contract_id,
            "field_contract_version": validated.field_contract_version,
            "semantic_parameters": list(validated.semantic_parameters),
        }
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")


def method_configuration_digest(
    semantic_payload: MethodConfigurationSemanticPayload,
) -> str:
    """Return SHA-256 of exactly the canonical semantic-payload bytes."""

    if not isinstance(semantic_payload, MethodConfigurationSemanticPayload):
        raise InvalidMethodConfigurationError(
            "method_configuration_digest requires MethodConfigurationSemanticPayload"
        )
    return hashlib.sha256(semantic_payload.canonical_json_bytes()).hexdigest()


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate serialized field: {key}")
        result[key] = value
    return result


class MethodConfiguration(_SerializedConfigurationContract):
    """Recoverable semantic payload plus its derived integrity digest."""

    semantic_payload: MethodConfigurationSemanticPayload
    configuration_sha256: _LowerSha256

    @model_validator(mode="after")
    def digest_matches_payload(self) -> Self:
        expected = method_configuration_digest(self.semantic_payload)
        if self.configuration_sha256 != expected:
            raise ValueError("configuration_sha256 does not match the semantic payload")
        return self

    @classmethod
    def from_serialized(
        cls,
        serialized: Mapping[str, object] | str | bytes | bytearray,
    ) -> Self:
        """Validate an exact serialized configuration envelope and its digest."""

        try:
            if isinstance(serialized, (str, bytes, bytearray)):
                decoded = json.loads(
                    serialized,
                    object_pairs_hook=_reject_duplicate_json_keys,
                    parse_constant=lambda value: (_ for _ in ()).throw(
                        ValueError(f"non-finite JSON constant: {value}")
                    ),
                )
            elif isinstance(serialized, Mapping):
                decoded = dict(serialized)
            else:
                raise TypeError("serialized method configuration must be JSON or a mapping")
            if not isinstance(decoded, dict):
                raise TypeError("serialized method configuration must be a JSON object")
            return cls.model_validate(decoded)
        except InvalidMethodConfigurationError:
            raise
        except (TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            raise InvalidMethodConfigurationError("invalid serialized method configuration") from exc

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MethodConfiguration):
            return NotImplemented
        return self.semantic_payload == other.semantic_payload

    def __hash__(self) -> int:
        return hash(self.semantic_payload)

def _resolve_method_name(method_name: MethodName | str) -> MethodName:
    if isinstance(method_name, MethodName):
        return method_name
    try:
        return MethodName(method_name)
    except (TypeError, ValueError) as exc:
        raise UnknownMethodError(f"unknown method identity: {method_name!r}") from exc


def _resolve_method_version(
    method_name: MethodName,
    method_version: MethodVersion | str,
) -> MethodVersion:
    try:
        resolved = method_version if isinstance(method_version, MethodVersion) else MethodVersion(method_version)
    except (TypeError, ValueError) as exc:
        raise UnsupportedMethodVersionError(
            f"unsupported method version: {method_version!r}"
        ) from exc
    if resolved not in _SUPPORTED_METHOD_VERSIONS[method_name]:
        raise UnsupportedMethodVersionError(
            f"method {method_name.value} does not support version {resolved.value}"
        )
    return resolved


def build_method_configuration(
    *,
    method_name: MethodName | str,
    method_version: MethodVersion | str,
    field_contract: FieldEvidenceContract,
) -> MethodConfiguration:
    """Build one immutable, closed, digest-validated method configuration."""

    resolved_name = _resolve_method_name(method_name)
    resolved_version = _resolve_method_version(resolved_name, method_version)
    if not isinstance(field_contract, FieldEvidenceContract):
        raise InvalidMethodConfigurationError("field_contract must be a FieldEvidenceContract")

    semantic_payload = MethodConfigurationSemanticPayload(
        schema_version=_METHOD_CONFIGURATION_SCHEMA_VERSION,
        method_name=resolved_name,
        method_version=resolved_version,
        field_contract_id=field_contract.contract_id,
        field_contract_version=field_contract.contract_version,
        semantic_parameters=(),
    )
    return MethodConfiguration(
        semantic_payload=semantic_payload,
        configuration_sha256=method_configuration_digest(semantic_payload),
    )


def _plain_detached(value: object) -> object:
    if isinstance(value, BaseModel):
        return deepcopy(value.model_dump(mode="python", round_trip=True, warnings=False))
    if isinstance(value, Mapping):
        return {deepcopy(key): _plain_detached(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_plain_detached(item) for item in value)
    if isinstance(value, list):
        return [_plain_detached(item) for item in value]
    return deepcopy(value)


def _detached_model[ModelT: BaseModel](
    model_type: type[ModelT],
    value: object,
    error_type: type[MethodError],
    label: str,
) -> ModelT:
    """Revalidate a deep detached representation of one accepted artifact."""

    try:
        return model_type.model_validate(_plain_detached(value))
    except MethodError:
        raise
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise error_type(f"invalid {label}") from exc


def _model_input(value: object, model_type: type[BaseModel]) -> dict[str, object] | None:
    if isinstance(value, model_type):
        return dict(value.__dict__)
    if isinstance(value, Mapping):
        return dict(value)
    return None


def _structural_model_input(
    value: object,
    model_type: type[BaseModel],
    *,
    required: frozenset[str],
    allowed: frozenset[str],
    error_type: type[MethodError],
    label: str,
) -> dict[str, object]:
    values = _model_input(value, model_type)
    if values is None:
        raise error_type(f"{label} must be a mapping or accepted model instance")
    missing = required - values.keys()
    unexpected = values.keys() - allowed
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append("missing fields: " + ", ".join(sorted(missing)))
        if unexpected:
            details.append("unexpected fields: " + ", ".join(sorted(unexpected)))
        raise error_type(f"malformed {label}: {'; '.join(details)}")
    return values


def _artifact_tuple(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, (tuple, list)):
        raise MalformedAuthoritativeInputError(f"{label} must be a finite tuple or list")
    return tuple(value)


def _same_json(first: object, second: object) -> bool:
    """Compare JSON projections without collapsing nested bool/int kinds."""

    if type(first) is not type(second):
        return False
    if isinstance(first, dict) and isinstance(second, dict):
        return first.keys() == second.keys() and all(
            _same_json(first[key], second[key]) for key in first
        )
    if isinstance(first, list) and isinstance(second, list):
        return len(first) == len(second) and all(
            _same_json(left, right) for left, right in zip(first, second, strict=True)
        )
    return first == second


def _same_s3_agreement_value(first: object, second: object) -> bool:
    """Reproduce accepted S3 agreement equality, including numeric equivalence."""

    if isinstance(first, (int, float)) and not isinstance(first, bool):
        if not isinstance(second, (int, float)) or isinstance(second, bool):
            return False
        try:
            return float(first) == float(second)
        except OverflowError:
            return False
    if isinstance(second, (int, float)) and not isinstance(second, bool):
        return False
    return type(first) is type(second) and first == second


def _source_stream(candidate: ComparableEvidence) -> str:
    """Reproduce accepted S3's canonical source-stream spelling."""

    return f"{candidate.source.value}:{candidate.source_instance or ''}"


def _selected_time(record: RuntimeObservation, basis: TimeBasis) -> datetime | None:
    if basis == TimeBasis.SOURCE_OBSERVATION_TIME:
        return record.observation_time
    return record.ingestion_time


def _query_order_key(
    record: RuntimeObservation,
    basis: TimeBasis,
) -> tuple[datetime, datetime, str]:
    selected = _selected_time(record, basis)
    if selected is None:
        raise MalformedAuthoritativeInputError("selected evidence-query time is unavailable")
    return selected, record.ingestion_time, str(record.observation_id)


def _matches_query(record: RuntimeObservation, request: EvidenceQueryRequest) -> bool:
    if request.session_mode == AssociationMode.SPECIFIC:
        if record.guardian_session_id != request.guardian_session_id:
            return False
    elif (
        request.session_mode == AssociationMode.UNASSOCIATED
        and record.guardian_session_id is not None
    ):
        return False
    if request.source_instance_mode == AssociationMode.SPECIFIC:
        if record.source_instance != request.source_instance:
            return False
    elif (
        request.source_instance_mode == AssociationMode.UNASSOCIATED
        and record.source_instance is not None
    ):
        return False
    if request.sources and record.source not in request.sources:
        return False
    if request.signals and record.signal not in request.signals:
        return False
    return all(
        type(record.provenance.get(selector.provenance_key))
        is type(selector.expected_value)
        and record.provenance.get(selector.provenance_key) == selector.expected_value
        for selector in request.subject_selectors
    )


def _canonical_pages(
    request: EvidenceQueryRequest,
    pages: tuple[EvidenceQueryResult, ...],
) -> tuple[EvidenceQueryResult, ...]:
    if not pages:
        raise MalformedAuthoritativeInputError("the complete evidence-query page collection is required")

    request_sha256 = hashlib.sha256(request.model_dump_json().encode("utf-8")).hexdigest()
    first = pages[0]
    watermark = first.dataset_watermark
    total_records = first.total_records
    common_metadata = (first.decoded_bytes, first.scanned_records, first.scanned_bytes)
    expected_page_count = max(1, (total_records + request.page_size - 1) // request.page_size)
    if expected_page_count > request.maximum_pages or len(pages) > request.maximum_pages:
        raise MethodResourceLimitError("evidence-query page collection exceeds its page ceiling")
    if total_records > request.maximum_records or first.decoded_bytes > request.maximum_decoded_bytes:
        raise MethodResourceLimitError("evidence-query result exceeds its declared resource ceiling")
    if first.scanned_records > request.maximum_scan_records:
        raise MethodResourceLimitError("evidence-query result exceeds its scan-record ceiling")
    if first.scanned_bytes > request.maximum_scan_bytes:
        raise MethodResourceLimitError("evidence-query result exceeds its scan-byte ceiling")
    if len(pages) != expected_page_count:
        raise MalformedAuthoritativeInputError("evidence-query page collection is incomplete")

    indexed: dict[int, EvidenceQueryResult] = {}
    for page in pages:
        if page.integrity != QueryIntegrity.VERIFIED:
            raise MalformedAuthoritativeInputError("evidence-query page integrity is not verified")
        if page.request_sha256 != request_sha256:
            raise MalformedAuthoritativeInputError("evidence-query page request digest mismatch")
        if page.dataset_watermark != watermark:
            raise MalformedAuthoritativeInputError("evidence-query page watermark mismatch")
        if page.total_records != total_records:
            raise MalformedAuthoritativeInputError("evidence-query pages disagree on total records")
        if (page.decoded_bytes, page.scanned_records, page.scanned_bytes) != common_metadata:
            raise MalformedAuthoritativeInputError("evidence-query pages disagree on authoritative metadata")
        if page.completeness == QueryCompleteness.HAS_MORE:
            continuation = page.continuation
            if continuation is None:
                raise MalformedAuthoritativeInputError("nonterminal page lacks continuation")
            if (
                continuation.request_sha256 != request_sha256
                or continuation.dataset_watermark != watermark
                or continuation.ordering_version != "selected-ingestion-uuid.v1"
            ):
                raise MalformedAuthoritativeInputError("evidence-query continuation binding mismatch")
            page_index = continuation.next_page - 1
            if continuation.next_offset != continuation.next_page * request.page_size:
                raise MalformedAuthoritativeInputError("evidence-query continuation position is incoherent")
        elif page.completeness == QueryCompleteness.COMPLETE:
            if page.continuation is not None:
                raise MalformedAuthoritativeInputError("terminal page cannot carry continuation")
            page_index = expected_page_count - 1
        else:
            raise MalformedAuthoritativeInputError("unsupported evidence-query completeness state")
        if page_index in indexed:
            raise MalformedAuthoritativeInputError("duplicate evidence-query page identity")
        indexed[page_index] = page

    if set(indexed) != set(range(expected_page_count)):
        raise MalformedAuthoritativeInputError("evidence-query page chain has a gap")
    canonical = tuple(indexed[index] for index in range(expected_page_count))
    for index, page in enumerate(canonical):
        terminal = index == expected_page_count - 1
        expected_records = (
            total_records - request.page_size * index
            if terminal
            else request.page_size
        )
        if len(page.records) != expected_records:
            raise MalformedAuthoritativeInputError("evidence-query page record accounting mismatch")
        if terminal != (page.completeness == QueryCompleteness.COMPLETE):
            raise MalformedAuthoritativeInputError("evidence-query terminal completeness mismatch")
        if index != 0 and page.predecessors:
            raise MalformedAuthoritativeInputError("predecessors are permitted only on the first page")
    if len(canonical[0].predecessors) > request.maximum_predecessor_records:
        raise MethodResourceLimitError("predecessor evidence exceeds its declared record ceiling")

    primary = tuple(record for page in canonical for record in page.records)
    predecessors = canonical[0].predecessors
    if primary != tuple(sorted(primary, key=lambda record: _query_order_key(record, request.time_basis))):
        raise MalformedAuthoritativeInputError("primary evidence transport order is contradictory")
    if predecessors != tuple(
        sorted(predecessors, key=lambda record: _query_order_key(record, request.time_basis))
    ):
        raise MalformedAuthoritativeInputError("predecessor evidence transport order is contradictory")

    try:
        predecessor_start = request.start_time - timedelta(
            seconds=request.predecessor_lookback_seconds
        )
    except (OverflowError, TypeError, ValueError) as exc:
        raise MalformedAuthoritativeInputError(
            "predecessor lookback cannot be represented by the authoritative time domain"
        ) from exc
    for record in primary:
        selected = _selected_time(record, request.time_basis)
        if (
            selected is None
            or not request.start_time < selected <= request.end_time
            or record.ingestion_time > request.as_of_cutoff
            or not _matches_query(record, request)
        ):
            raise MalformedAuthoritativeInputError("primary observation contradicts the bound query")
    for record in predecessors:
        selected = _selected_time(record, request.time_basis)
        if (
            selected is None
            or not predecessor_start < selected <= request.start_time
            or record.ingestion_time > request.as_of_cutoff
            or not _matches_query(record, request)
        ):
            raise MalformedAuthoritativeInputError("predecessor observation contradicts the bound query")
    return canonical


def _validate_conflict_binding(
    contract: ComparisonContract,
    request: ComparisonRequest,
    candidates: tuple[ComparableEvidence, ...],
    result: ConflictDetectionResult,
) -> None:
    if (
        result.contract_id != contract.contract_id
        or result.contract_version != contract.contract_version
        or result.comparison_basis != contract.comparison_basis
    ):
        raise MalformedS3ArtifactError("conflict result does not bind to its comparison contract")
    if (
        result.affected_field_key != request.affected_field_key
        or result.quantity_id != request.quantity_id
    ):
        raise MalformedS3ArtifactError("conflict result does not bind to its comparison request")
    if result.method_name != CONFLICT_METHOD or result.method_version != CONFLICT_METHOD_VERSION:
        raise MalformedS3ArtifactError("unsupported conflict-detection method identity")

    declarations = tuple(
        quantity for quantity in contract.quantities if quantity.quantity_id == request.quantity_id
    )
    if len(declarations) != 1:
        raise MalformedS3ArtifactError("comparison request quantity is not declared exactly once")
    allowed_signals = set(declarations[0].signals)
    candidate_ids = [candidate.observation_id for candidate in candidates]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise DuplicateObservationIdentityError("duplicate candidate observation identity")
    for candidate in candidates:
        if candidate.signal not in allowed_signals:
            raise MalformedS3ArtifactError("candidate signal is outside the declared quantity")
        if candidate.identity.observation_id != candidate.observation_id:
            raise MalformedS3ArtifactError("candidate identity belongs to another observation")
        if (
            candidate.identity.method_name != SUBJECT_RESOLUTION_METHOD
            or candidate.identity.method_version != SUBJECT_RESOLUTION_METHOD_VERSION
        ):
            raise MalformedS3ArtifactError("unsupported candidate identity-resolution method")

    accounted = [
        identifier
        for conflict in result.conflicts
        for identifier in conflict.participant_evidence_ids
    ]
    accounted += [
        identifier
        for agreement in result.agreements
        for identifier in agreement.participant_evidence_ids
    ]
    accounted += [entry.observation_id for entry in result.not_compared]
    if len(set(accounted)) != len(accounted) or set(accounted) != set(candidate_ids):
        raise MalformedS3ArtifactError("conflict result does not account for candidates exactly once")

    candidate_map = {candidate.observation_id: candidate for candidate in candidates}
    for conflict in result.conflicts:
        if (
            conflict.affected_field_key != request.affected_field_key
            or conflict.comparison_contract_id != contract.contract_id
            or conflict.comparison_contract_version != contract.contract_version
            or conflict.comparison_basis != contract.comparison_basis
        ):
            raise MalformedS3ArtifactError("embedded conflict binding is contradictory")
        if (
            conflict.resolution_status != ConflictResolutionStatus.UNRESOLVED
            or conflict.selected_evidence_ids
            or conflict.rejected_evidence_ids
            or conflict.resolution_rule_id is not None
            or conflict.resolution_rule_version is not None
        ):
            raise MalformedS3ArtifactError("conflict binding claims an unsupported resolved state")
        expected_participants = tuple(sorted(conflict.participant_evidence_ids, key=str))
        if conflict.participant_evidence_ids != expected_participants:
            raise MalformedS3ArtifactError(
                "conflict participant order is not producer-canonical"
            )
        expected_identity = request.expected_identity
        expected_conflict_id = deterministic_uuid(
            "state-conflict",
            (
                request.affected_field_key,
                ConflictKind(conflict.kind).value,
                contract.contract_id,
                contract.contract_version,
                contract.comparison_basis,
                request.quantity_id,
                expected_identity.subject_id,
                expected_identity.workload_id or "",
                expected_identity.algorithm_id or "",
                *(str(identifier) for identifier in expected_participants),
                ConflictResolutionStatus.UNRESOLVED.value,
                conflict.reason,
            ),
        )
        if conflict.conflict_id != expected_conflict_id:
            raise MalformedS3ArtifactError("conflict identity is not the deterministic S3 identity")
    for agreement in result.agreements:
        if (
            agreement.quantity_id != request.quantity_id
            or agreement.comparison_basis != contract.comparison_basis
        ):
            raise MalformedS3ArtifactError("agreement quantity or basis is contradictory")
        participants = tuple(candidate_map[identifier] for identifier in agreement.participant_evidence_ids)
        expected_participant_ids = tuple(
            sorted((participant.observation_id for participant in participants), key=str)
        )
        if agreement.participant_evidence_ids != expected_participant_ids:
            raise MalformedS3ArtifactError("agreement participant order is not producer-canonical")
        expected_source_streams = tuple(
            sorted({_source_stream(participant) for participant in participants})
        )
        if agreement.source_streams != expected_source_streams:
            raise MalformedS3ArtifactError("agreement source-stream provenance is contradictory")
        if any(
            participant.unit != agreement.unit
            or participant.effective_basis != agreement.effective_basis
            or not _same_s3_agreement_value(participant.value, agreement.agreed_value)
            for participant in participants
        ):
            raise MalformedS3ArtifactError("agreement projection contradicts its candidates")
        spread = (
            max(participant.effective_time for participant in participants)
            - min(participant.effective_time for participant in participants)
        ).total_seconds()
        if spread != agreement.effective_time_spread_seconds:
            raise MalformedS3ArtifactError("agreement time spread contradicts its candidates")


class ConflictBinding(_DefensiveSnapshotStateContract):
    """One detached, internally coherent authoritative S3 comparison bundle."""

    comparison_contract: ComparisonContract
    comparison_request: ComparisonRequest
    candidates: tuple[ComparableEvidence, ...]
    result: ConflictDetectionResult

    @model_validator(mode="before")
    @classmethod
    def detach_and_bind(cls, value: object) -> object:
        required = {"comparison_contract", "comparison_request", "candidates", "result"}
        values = _structural_model_input(
            value,
            cls,
            required=frozenset(required),
            allowed=frozenset(required),
            error_type=MalformedS3ArtifactError,
            label="conflict binding",
        )
        contract = _detached_model(
            ComparisonContract,
            values["comparison_contract"],
            MalformedS3ArtifactError,
            "comparison contract",
        )
        request = _detached_model(
            ComparisonRequest,
            values["comparison_request"],
            MalformedS3ArtifactError,
            "comparison request",
        )
        try:
            raw_candidates = _artifact_tuple(values["candidates"], "conflict candidates")
        except MalformedAuthoritativeInputError as exc:
            raise MalformedS3ArtifactError("invalid conflict candidates") from exc
        candidates = tuple(
            sorted(
                (
                    _detached_model(
                        ComparableEvidence,
                        candidate,
                        MalformedS3ArtifactError,
                        "comparable evidence",
                    )
                    for candidate in raw_candidates
                ),
                key=lambda candidate: str(candidate.observation_id),
            )
        )
        result = _detached_model(
            ConflictDetectionResult,
            values["result"],
            MalformedS3ArtifactError,
            "conflict-detection result",
        )
        _validate_conflict_binding(contract, request, candidates, result)
        values.update(
            comparison_contract=contract,
            comparison_request=request,
            candidates=candidates,
            result=result,
        )
        return values


def _validate_field_binding(
    field_request: FieldRequest,
    field_contract: FieldEvidenceContract,
    query_request: EvidenceQueryRequest,
) -> None:
    if field_request.field_key != field_contract.field_key:
        raise FieldContractBindingError("field request and field contract keys disagree")
    if field_request.subject_scope != field_contract.subject_scope:
        raise FieldContractBindingError("field request and field contract subject scopes disagree")
    reference_time = query_request.end_time
    try:
        expected_start = reference_time - timedelta(seconds=field_contract.window_seconds)
    except (OverflowError, TypeError, ValueError) as exc:
        raise FieldContractBindingError("field evidence window cannot be represented") from exc
    if query_request.start_time != expected_start:
        raise FieldContractBindingError("evidence-query start does not match the field window")
    if query_request.as_of_cutoff != reference_time:
        raise FieldContractBindingError("evidence-query cutoff does not match its reference time")
    if query_request.time_basis != field_contract.temporal_basis:
        raise FieldContractBindingError("evidence-query time basis disagrees with the field contract")
    if query_request.maximum_records > field_contract.maximum_records:
        raise MethodResourceLimitError("evidence-query record ceiling exceeds the field contract")
    if query_request.maximum_decoded_bytes > field_contract.maximum_decoded_bytes:
        raise MethodResourceLimitError("evidence-query byte ceiling exceeds the field contract")
    if query_request.predecessor_lookback_seconds != field_contract.predecessor_lookback_seconds:
        raise FieldContractBindingError("predecessor lookback disagrees with the field contract")


def _validate_admissions(
    admissions: tuple[AdmissionAssessment, ...],
    observations: tuple[RuntimeObservation, ...],
    field_contract: FieldEvidenceContract,
    reference_time: datetime,
) -> None:
    identifiers = [assessment.observation_id for assessment in admissions]
    if len(set(identifiers)) != len(identifiers):
        raise MalformedS3ArtifactError("duplicate admission assessment")
    observation_ids = {record.observation_id for record in observations}
    if set(identifiers) != observation_ids:
        raise MalformedS3ArtifactError("admission assessments do not account for every observation")
    expected_start = reference_time - timedelta(seconds=field_contract.window_seconds)
    observation_map = {record.observation_id: record for record in observations}
    for assessment in admissions:
        record = observation_map[assessment.observation_id]
        if (
            assessment.field_contract_id != field_contract.contract_id
            or assessment.field_contract_version != field_contract.contract_version
        ):
            raise MalformedS3ArtifactError("admission field-contract identity mismatch")
        if assessment.temporal_basis != field_contract.temporal_basis:
            raise MalformedS3ArtifactError("admission temporal basis mismatch")
        if assessment.window_start != expected_start or assessment.window_end != reference_time:
            raise MalformedS3ArtifactError("admission window does not bind to the reference time")
        if assessment.method_name != ADMISSION_METHOD or assessment.method_version != ADMISSION_METHOD_VERSION:
            raise MalformedS3ArtifactError("unsupported admission method identity")
        if (
            assessment.input_quality != record.quality
            or assessment.input_quality_conditions != record.quality_conditions
            or assessment.recorded_freshness != record.freshness
        ):
            raise MalformedS3ArtifactError("admission contradicts preserved observation state")


def _validate_identities(
    identities: tuple[IdentityResolution, ...],
    observations: tuple[RuntimeObservation, ...],
) -> None:
    identifiers = [identity.observation_id for identity in identities]
    if len(set(identifiers)) != len(identifiers):
        raise MalformedS3ArtifactError("duplicate identity resolution")
    if set(identifiers) != {record.observation_id for record in observations}:
        raise MalformedS3ArtifactError("identity resolutions do not account for every observation")
    mapping_versions = {(identity.mapping_id, identity.mapping_version) for identity in identities}
    if len(mapping_versions) > 1:
        raise MalformedS3ArtifactError("identity resolutions use mixed mapping identities or versions")
    if any(
        identity.method_name != SUBJECT_RESOLUTION_METHOD
        or identity.method_version != SUBJECT_RESOLUTION_METHOD_VERSION
        for identity in identities
    ):
        raise MalformedS3ArtifactError("unsupported identity-resolution method identity")


def _validate_segment(
    segment: AnalyticalSegment,
    observations: Mapping[UUID, RuntimeObservation],
    identities: Mapping[UUID, IdentityResolution],
    contract: ContinuityContract,
) -> None:
    if (
        segment.continuity_contract_id != contract.contract_id
        or segment.continuity_contract_version != contract.contract_version
        or segment.continuity_rule != contract.continuity_rule
        or segment.ordering_basis != contract.ordering_basis
        or segment.minimum_segment_samples != contract.minimum_segment_samples
        or segment.minimum_segment_elapsed_seconds != contract.minimum_segment_elapsed_seconds
        or segment.method_name != CONTINUITY_METHOD
        or segment.method_version != CONTINUITY_METHOD_VERSION
    ):
        raise MalformedS3ArtifactError("segment does not bind to the continuity contract")
    members = tuple(observations[identifier] for identifier in segment.observation_ids)
    expected_order = tuple(
        sorted(members, key=lambda record: _query_order_key(record, contract.ordering_basis))
    )
    if members != expected_order:
        raise MalformedS3ArtifactError("segment observation order contradicts its ordering basis")
    if any(
        record.source != segment.source
        or record.source_instance != segment.source_instance
        or record.signal != segment.signal
        for record in members
    ):
        raise MalformedS3ArtifactError("segment stream provenance contradicts its observations")
    member_identities = tuple(identities[record.observation_id] for record in members)
    if any(identity.scope_key != segment.identity_signature for identity in member_identities):
        raise MalformedS3ArtifactError("segment identity signature contradicts authoritative identity")
    anchor_identity = member_identities[0]
    if (
        segment.subject_id != anchor_identity.subject.resolved_id
        or segment.workload_id != anchor_identity.workload.resolved_id
        or segment.algorithm_id != anchor_identity.algorithm.resolved_id
    ):
        raise MalformedS3ArtifactError("segment scoped identities contradict its anchor identity")
    selected_times = tuple(_selected_time(record, contract.ordering_basis) for record in members)
    if any(value is None for value in selected_times):
        raise MalformedS3ArtifactError("assigned segment evidence lacks its ordering time")
    start = selected_times[0]
    end = selected_times[-1]
    if start is None or end is None:
        raise MalformedS3ArtifactError("segment time range is unavailable")
    if (
        segment.start_time != start
        or segment.end_time != end
        or segment.elapsed_seconds != (end - start).total_seconds()
    ):
        raise MalformedS3ArtifactError("segment interval contradicts its ordered observations")
    expected_segment_id = deterministic_digest(
        "continuity-segment",
        (
            contract.contract_id,
            contract.contract_version,
            contract.continuity_rule,
            contract.ordering_basis.value,
            segment.source.value,
            segment.source_instance or "",
            segment.signal,
            segment.identity_signature,
            str(segment.anchor_observation_id),
            *(str(identifier) for identifier in segment.observation_ids),
        ),
    )
    if segment.segment_id != expected_segment_id:
        raise MalformedS3ArtifactError("segment identity is not the deterministic S3 identity")


def _validate_continuity(
    contract: ContinuityContract,
    result: ContinuityResult,
    observations: tuple[RuntimeObservation, ...],
    identities: tuple[IdentityResolution, ...],
    field_contract: FieldEvidenceContract,
) -> None:
    if (
        contract.contract_id != field_contract.contract_id
        or contract.contract_version != field_contract.contract_version
        or contract.continuity_rule != field_contract.continuity_rule
        or contract.ordering_basis != field_contract.temporal_basis
        or contract.maximum_gap_seconds != field_contract.maximum_gap_seconds
        or contract.minimum_segment_samples != field_contract.minimum_samples
        or contract.minimum_segment_elapsed_seconds != field_contract.minimum_span_seconds
    ):
        raise MalformedS3ArtifactError("continuity contract is not derived from the field contract")
    if (
        result.contract_id != contract.contract_id
        or result.contract_version != contract.contract_version
        or result.continuity_rule != contract.continuity_rule
        or result.ordering_basis != contract.ordering_basis
        or result.method_name != CONTINUITY_METHOD
        or result.method_version != CONTINUITY_METHOD_VERSION
    ):
        raise MalformedS3ArtifactError("continuity result does not bind to its contract")

    observation_map = {record.observation_id: record for record in observations}
    identity_map = {identity.observation_id: identity for identity in identities}
    assigned = [identifier for segment in result.segments for identifier in segment.observation_ids]
    unassigned = [entry.observation_id for entry in result.unassigned]
    if len(set(assigned)) != len(assigned):
        raise MalformedS3ArtifactError("duplicate continuity segment membership")
    if len(set(unassigned)) != len(unassigned):
        raise MalformedS3ArtifactError("duplicate continuity unassigned membership")
    if set(assigned) & set(unassigned):
        raise MalformedS3ArtifactError("observation is both assigned and unassigned")
    if set(assigned) | set(unassigned) != set(observation_map):
        raise MalformedS3ArtifactError("continuity membership does not exactly account for observations")
    if any(identifier not in observation_map for identifier in (*assigned, *unassigned)):
        raise MalformedS3ArtifactError("continuity references an unknown observation")
    expected_unassigned = tuple(
        sorted(result.unassigned, key=lambda entry: str(entry.observation_id))
    )
    if result.unassigned != expected_unassigned:
        raise MalformedS3ArtifactError(
            "continuity unassigned order is not producer-canonical"
        )

    if [segment.segment_index for segment in result.segments] != list(range(len(result.segments))):
        raise MalformedS3ArtifactError("continuity segment indices are not canonical")
    segment_ids = [segment.segment_id for segment in result.segments]
    if any(not identifier for identifier in segment_ids) or len(set(segment_ids)) != len(segment_ids):
        raise MalformedS3ArtifactError("continuity segment identities are invalid or duplicated")
    if tuple(segment.boundary for segment in result.segments) != result.boundaries:
        raise MalformedS3ArtifactError("continuity boundary inventory contradicts its segments")

    prior_stream: tuple[str, str, str] | None = None
    prior_segment: AnalyticalSegment | None = None
    prior_order_key: tuple[str, str, str, datetime, datetime, str] | None = None
    for segment in result.segments:
        _validate_segment(segment, observation_map, identity_map, contract)
        stream = (segment.source.value, segment.source_instance or "", segment.signal)
        anchor = observation_map[segment.anchor_observation_id]
        selected_time = _selected_time(anchor, contract.ordering_basis)
        if selected_time is None:
            raise MalformedS3ArtifactError("continuity segment anchor lacks its ordering time")
        order_key = (
            *stream,
            selected_time,
            anchor.ingestion_time,
            str(anchor.observation_id),
        )
        if prior_order_key is not None and order_key <= prior_order_key:
            raise MalformedS3ArtifactError(
                "continuity segment order is not producer-canonical"
            )
        boundary = segment.boundary
        if prior_stream != stream:
            if (
                boundary.previous_observation_id is not None
                or boundary.elapsed_seconds is not None
                or boundary.reasons != (BreakReason.SEGMENT_START,)
                or boundary.evidence
            ):
                raise MalformedS3ArtifactError("first stream boundary has contradictory provenance")
        else:
            if prior_segment is None:
                raise MalformedS3ArtifactError("continuity boundary chain is unavailable")
            expected_previous = prior_segment.observation_ids[-1]
            expected_elapsed = (segment.start_time - prior_segment.end_time).total_seconds()
            if (
                boundary.previous_observation_id != expected_previous
                or boundary.elapsed_seconds != expected_elapsed
                or BreakReason.SEGMENT_START in boundary.reasons
            ):
                raise MalformedS3ArtifactError("continuity boundary chain is contradictory")
        prior_stream = stream
        prior_segment = segment
        prior_order_key = order_key


def _validate_candidate_projection(
    candidate: ComparableEvidence,
    observation: RuntimeObservation,
    identity: IdentityResolution,
) -> None:
    if (
        candidate.observation_id != observation.observation_id
        or candidate.source != observation.source
        or candidate.source_instance != observation.source_instance
        or candidate.signal != observation.signal
        or candidate.unit != observation.unit
        or candidate.correlation_id != observation.correlation_id
        or not _same_json(candidate.value, observation.value)
    ):
        raise MalformedS3ArtifactError("conflict candidate contradicts its canonical observation")
    effective_time = _selected_time(observation, candidate.effective_basis)
    if effective_time is None or candidate.effective_time != effective_time:
        raise MalformedS3ArtifactError("candidate effective time contradicts its canonical observation")
    if candidate.identity != identity:
        raise MalformedS3ArtifactError("candidate identity contradicts authoritative identity")


def _validate_conflicts_against_authority(
    bindings: tuple[ConflictBinding, ...],
    observations: tuple[RuntimeObservation, ...],
    identities: tuple[IdentityResolution, ...],
    field_request: FieldRequest,
    field_contract: FieldEvidenceContract,
) -> None:
    observation_map = {record.observation_id: record for record in observations}
    identity_map = {identity.observation_id: identity for identity in identities}
    for binding in bindings:
        if binding.comparison_request.affected_field_key != field_request.field_key:
            raise MalformedS3ArtifactError("conflict binding belongs to another field")
        if binding.comparison_request.expected_identity.subject_id != field_request.subject_scope:
            raise MalformedS3ArtifactError("comparison request subject does not bind to the field request")
        if (
            binding.comparison_contract.maximum_alignment_seconds
            != field_contract.maximum_alignment_seconds
        ):
            raise MalformedS3ArtifactError("comparison alignment does not bind to the field contract")
        for candidate in binding.candidates:
            if candidate.observation_id not in observation_map:
                raise MalformedS3ArtifactError("conflict candidate references an unknown observation")
            if candidate.effective_basis != field_contract.temporal_basis:
                raise MalformedS3ArtifactError("candidate temporal basis contradicts the field contract")
            _validate_candidate_projection(
                candidate,
                observation_map[candidate.observation_id],
                identity_map[candidate.observation_id],
            )


def _conflict_binding_key(binding: ConflictBinding) -> str:
    return json.dumps(
        binding.model_dump(mode="json", round_trip=True),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


class AuthoritativeMethodInput(_DefensiveSnapshotStateContract):
    """Detached structural envelope over one coherent S2/S3 field bundle."""

    field_request: FieldRequest
    field_contract: FieldEvidenceContract
    evidence_query_request: EvidenceQueryRequest
    evidence_query_results: tuple[EvidenceQueryResult, ...]
    admissions: tuple[AdmissionAssessment, ...]
    identities: tuple[IdentityResolution, ...]
    continuity_contract: ContinuityContract
    continuity_result: ContinuityResult
    conflict_bindings: tuple[ConflictBinding, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def detach_and_bind(cls, value: object) -> object:
        required = {
            "field_request",
            "field_contract",
            "evidence_query_request",
            "evidence_query_results",
            "admissions",
            "identities",
            "continuity_contract",
            "continuity_result",
        }
        allowed = {*required, "conflict_bindings"}
        values = _structural_model_input(
            value,
            cls,
            required=frozenset(required),
            allowed=frozenset(allowed),
            error_type=MalformedAuthoritativeInputError,
            label="authoritative method input",
        )

        field_request = _detached_model(
            FieldRequest, values["field_request"], FieldContractBindingError, "field request"
        )
        field_contract = _detached_model(
            FieldEvidenceContract,
            values["field_contract"],
            FieldContractBindingError,
            "field evidence contract",
        )
        query_request = _detached_model(
            EvidenceQueryRequest,
            values["evidence_query_request"],
            MalformedAuthoritativeInputError,
            "evidence-query request",
        )
        _validate_field_binding(field_request, field_contract, query_request)

        raw_pages = _artifact_tuple(values["evidence_query_results"], "evidence-query results")
        raw_admissions = _artifact_tuple(values["admissions"], "admission assessments")
        raw_identities = _artifact_tuple(values["identities"], "identity resolutions")
        raw_bindings = _artifact_tuple(values.get("conflict_bindings", ()), "conflict bindings")
        pages = tuple(
            _detached_model(
                EvidenceQueryResult,
                page,
                MalformedAuthoritativeInputError,
                "evidence-query result",
            )
            for page in raw_pages
        )
        pages = _canonical_pages(query_request, pages)
        primary = tuple(record for page in pages for record in page.records)
        predecessors = pages[0].predecessors
        observations = predecessors + primary
        observation_ids = [record.observation_id for record in observations]
        if len(set(observation_ids)) != len(observation_ids):
            raise DuplicateObservationIdentityError("duplicate authoritative observation identity")

        admissions = tuple(
            sorted(
                (
                    _detached_model(
                        AdmissionAssessment,
                        assessment,
                        MalformedS3ArtifactError,
                        "admission assessment",
                    )
                    for assessment in raw_admissions
                ),
                key=lambda assessment: str(assessment.observation_id),
            )
        )
        identities = tuple(
            sorted(
                (
                    _detached_model(
                        IdentityResolution,
                        identity,
                        MalformedS3ArtifactError,
                        "identity resolution",
                    )
                    for identity in raw_identities
                ),
                key=lambda identity: str(identity.observation_id),
            )
        )
        continuity_contract = _detached_model(
            ContinuityContract,
            values["continuity_contract"],
            MalformedS3ArtifactError,
            "continuity contract",
        )
        continuity_result = _detached_model(
            ContinuityResult,
            values["continuity_result"],
            MalformedS3ArtifactError,
            "continuity result",
        )
        bindings = tuple(
            sorted(
                (
                    _detached_model(
                        ConflictBinding,
                        binding,
                        MalformedS3ArtifactError,
                        "conflict binding",
                    )
                    for binding in raw_bindings
                ),
                key=_conflict_binding_key,
            )
        )

        _validate_admissions(admissions, observations, field_contract, query_request.end_time)
        _validate_identities(identities, observations)
        _validate_continuity(
            continuity_contract,
            continuity_result,
            observations,
            identities,
            field_contract,
        )
        _validate_conflicts_against_authority(
            bindings,
            observations,
            identities,
            field_request,
            field_contract,
        )
        values.update(
            field_request=field_request,
            field_contract=field_contract,
            evidence_query_request=query_request,
            evidence_query_results=pages,
            admissions=admissions,
            identities=identities,
            continuity_contract=continuity_contract,
            continuity_result=continuity_result,
            conflict_bindings=bindings,
        )
        return values

    @property
    def state_reference_time(self) -> datetime:
        return self.evidence_query_request.end_time

    @property
    def canonical_page_order(self) -> tuple[EvidenceQueryResult, ...]:
        return self.evidence_query_results

    @property
    def primary_observations(self) -> tuple[RuntimeObservation, ...]:
        return tuple(record for page in self.evidence_query_results for record in page.records)

    @property
    def predecessor_observations(self) -> tuple[RuntimeObservation, ...]:
        return self.evidence_query_results[0].predecessors

    @property
    def observations_by_id(self) -> Mapping[UUID, RuntimeObservation]:
        return MappingProxyType(
            {
                record.observation_id: record
                for record in (*self.predecessor_observations, *self.primary_observations)
            }
        )

    @property
    def admission_map(self) -> Mapping[UUID, AdmissionAssessment]:
        return MappingProxyType({item.observation_id: item for item in self.admissions})

    @property
    def identity_map(self) -> Mapping[UUID, IdentityResolution]:
        return MappingProxyType({item.observation_id: item for item in self.identities})

    @property
    def observation_segment_index(self) -> Mapping[UUID, str]:
        return MappingProxyType(
            {
                identifier: segment.segment_id
                for segment in self.continuity_result.segments
                for identifier in segment.observation_ids
            }
        )


def _validate_support_configuration(
    configuration: MethodConfiguration,
    authoritative_input: AuthoritativeMethodInput,
) -> _MethodSupportView | None:
    payload = configuration.semantic_payload
    field_contract = authoritative_input.field_contract

    if (
        payload.field_contract_id != field_contract.contract_id
        or payload.field_contract_version != field_contract.contract_version
    ):
        raise FieldContractBindingError(
            "method configuration does not bind to the authoritative field contract"
        )

    return _support_view_for_method(payload.method_name)


def _initial_support_exclusion_reason(
    observation: RuntimeObservation,
    authoritative_input: AuthoritativeMethodInput,
    support_view: _MethodSupportView,
) -> Name | None:
    admission = authoritative_input.admission_map[observation.observation_id]

    eligible = (
        admission.eligible_for_current
        if support_view == "CURRENT"
        else admission.eligible_for_history
    )
    if not eligible:
        return (
            f"admission:{admission.outcome.value}:"
            f"{admission.primary_reason}"
        )

    identity = authoritative_input.identity_map[observation.observation_id]
    subject = identity.subject

    if subject.status != IdentityComponentStatus.RESOLVED:
        return f"identity:subject:{subject.reason}"

    if subject.resolved_id != authoritative_input.field_request.subject_scope:
        return "identity:subject:resolved_id_does_not_match_requested_scope"

    return None


def _field_compatibility_exclusion_reason(
    observation: RuntimeObservation,
    authoritative_input: AuthoritativeMethodInput,
) -> Name | None:
    requirements = (
        authoritative_input.field_contract.required_signals
        + authoritative_input.field_contract.optional_signals
    )
    matching = tuple(
        requirement
        for requirement in requirements
        if requirement.source == observation.source.value
        and requirement.signal == observation.signal
    )

    if len(matching) != 1:
        raise MalformedS3ArtifactError(
            "observation source/signal is not uniquely declared by the field contract"
        )

    requirement = matching[0]

    if observation.unit != requirement.unit:
        return "unit_conversion_not_authorized"

    return None


type _ConflictDispositionKind = Literal[
    "AGREEMENT",
    "CONFLICT",
    "NOT_COMPARED",
]


def _conflict_binding_dispositions(
    binding: ConflictBinding,
) -> Mapping[UUID, tuple[_ConflictDispositionKind, str]]:
    dispositions: dict[
        UUID,
        tuple[_ConflictDispositionKind, str],
    ] = {}

    for agreement in binding.result.agreements:
        for observation_id in agreement.participant_evidence_ids:
            dispositions[observation_id] = (
                "AGREEMENT",
                "authoritative_s3_comparable_agreement",
            )

    for conflict in binding.result.conflicts:
        for observation_id in conflict.participant_evidence_ids:
            dispositions[observation_id] = (
                "CONFLICT",
                f"conflict:{conflict.kind.value}:{conflict.reason}",
            )

    for entry in binding.result.not_compared:
        dispositions[entry.observation_id] = (
            "NOT_COMPARED",
            f"not_compared:{entry.reason}",
        )

    candidate_ids = {
        candidate.observation_id
        for candidate in binding.candidates
    }

    if set(dispositions) != candidate_ids:
        raise MalformedS3ArtifactError(
            "conflict binding disposition coverage is incomplete"
        )

    if len(dispositions) != len(binding.candidates):
        raise MalformedS3ArtifactError(
            "conflict binding disposition accounting is not one-to-one"
        )

    return MappingProxyType(dispositions)


def _historical_segment_binding(
    authoritative_input: AuthoritativeMethodInput,
    observation_ids: tuple[UUID, ...],
) -> tuple[str, tuple[UUID, ...]] | None:
    if not observation_ids:
        return None

    if len(set(observation_ids)) != len(observation_ids):
        raise MalformedS3ArtifactError(
            "historical support contains duplicate observation identity"
        )

    authoritative_ids = set(authoritative_input.observations_by_id)
    unknown = tuple(
        observation_id
        for observation_id in observation_ids
        if observation_id not in authoritative_ids
    )
    if unknown:
        raise MalformedS3ArtifactError(
            "historical support references unknown authoritative evidence"
        )

    segment_index = authoritative_input.observation_segment_index

    if any(observation_id not in segment_index for observation_id in observation_ids):
        return None

    segment_ids = {
        segment_index[observation_id]
        for observation_id in observation_ids
    }
    if len(segment_ids) != 1:
        return None

    segment_id = next(iter(segment_ids))
    matching_segments = tuple(
        segment
        for segment in authoritative_input.continuity_result.segments
        if segment.segment_id == segment_id
    )
    if len(matching_segments) != 1:
        raise MalformedS3ArtifactError(
            "historical support segment identity is not uniquely authoritative"
        )

    segment = matching_segments[0]

    if not segment.evidence_sufficient_for_derivation:
        return None

    requested = set(observation_ids)
    ordered_observation_ids = tuple(
        observation_id
        for observation_id in segment.observation_ids
        if observation_id in requested
    )

    if set(ordered_observation_ids) != requested:
        raise MalformedS3ArtifactError(
            "historical support disagrees with authoritative segment membership"
        )

    return segment.segment_id, ordered_observation_ids


type _SupportStreamIdentity = tuple[str, str | None, str]


def _support_stream_identity(
    observation: RuntimeObservation,
) -> _SupportStreamIdentity:
    return (
        observation.source.value,
        observation.source_instance,
        observation.signal,
    )


def _canonical_considered_observations(
    authoritative_input: AuthoritativeMethodInput,
) -> tuple[RuntimeObservation, ...]:
    observation_map = authoritative_input.observations_by_id
    return tuple(
        observation_map[observation_id]
        for observation_id in sorted(
            observation_map,
            key=str,
        )
    )


def _initial_support_population(
    authoritative_input: AuthoritativeMethodInput,
    support_view: _MethodSupportView,
) -> tuple[
    tuple[RuntimeObservation, ...],
    Mapping[UUID, Name],
]:
    eligible: list[RuntimeObservation] = []
    exclusions: dict[UUID, Name] = {}

    for observation in _canonical_considered_observations(
        authoritative_input
    ):
        reason = _initial_support_exclusion_reason(
            observation,
            authoritative_input,
            support_view,
        )
        if reason is None:
            reason = _field_compatibility_exclusion_reason(
                observation,
                authoritative_input,
            )

        if reason is None:
            eligible.append(observation)
        else:
            exclusions[observation.observation_id] = reason

    return tuple(eligible), MappingProxyType(exclusions)


def _current_multi_stream_support(
    configuration: MethodConfiguration,
    authoritative_input: AuthoritativeMethodInput,
) -> AuthoritativeAnalyticalSet | MethodNoResult | None:
    support_view = _validate_support_configuration(
        configuration,
        authoritative_input,
    )
    if support_view != "CURRENT":
        return None

    eligible, exclusions = _initial_support_population(
        authoritative_input,
        support_view,
    )

    if not eligible:
        return None

    stream_identities = {
        _support_stream_identity(observation)
        for observation in eligible
    }
    if len(stream_identities) <= 1:
        return None

    eligible_ids = {
        observation.observation_id
        for observation in eligible
    }

    full_agreements = 0
    full_conflict_dispositions: list[
        Mapping[UUID, tuple[_ConflictDispositionKind, str]]
    ] = []

    for binding in authoritative_input.conflict_bindings:
        dispositions = _conflict_binding_dispositions(binding)

        for agreement in binding.result.agreements:
            if set(agreement.participant_evidence_ids) == eligible_ids:
                full_agreements += 1

        for conflict in binding.result.conflicts:
            if set(conflict.participant_evidence_ids) == eligible_ids:
                full_conflict_dispositions.append(dispositions)

    if full_conflict_dispositions:
        conflict_evidence_use: list[MethodEvidenceUse] = []

        for observation in _canonical_considered_observations(
            authoritative_input
        ):
            observation_id = observation.observation_id

            if observation_id in exclusions:
                reason = exclusions[observation_id]
            else:
                conflict_reasons: set[str] = set()

                for dispositions in full_conflict_dispositions:
                    disposition = dispositions.get(observation_id)

                    if (
                        disposition is not None
                        and disposition[0] == "CONFLICT"
                    ):
                        conflict_reasons.add(disposition[1])

                if not conflict_reasons:
                    return None

                # Presentation-only canonicalization.
                #
                # MethodEvidenceUse permits one exclusion reason per
                # observation.  Selecting the lexical minimum here does
                # NOT resolve a conflict, choose an authority, authorize
                # support, or rank a provider.  Every candidate reason
                # originates from an accepted S3 conflict artifact and
                # the semantic outcome remains UNRESOLVED_CONFLICT.
                reason = min(conflict_reasons)

            conflict_evidence_use.append(
                MethodEvidenceUse(
                    observation_id=observation_id,
                    role="EXCLUDED",
                    reason=reason,
                )
            )

        return MethodNoResult(
            configuration=configuration,
            reason=MethodNoResultReason.UNRESOLVED_CONFLICT,
            evidence_use=tuple(conflict_evidence_use),
        )

    if not full_agreements:
        no_single_evidence_use: list[MethodEvidenceUse] = []

        for observation in _canonical_considered_observations(
            authoritative_input
        ):
            observation_id = observation.observation_id

            if observation_id in exclusions:
                reason = exclusions[observation_id]
            else:
                reason = "method:no_single_comparable_analytical_set"

            no_single_evidence_use.append(
                MethodEvidenceUse(
                    observation_id=observation_id,
                    role="EXCLUDED",
                    reason=reason,
                )
            )

        return MethodNoResult(
            configuration=configuration,
            reason=(
                MethodNoResultReason.NO_SINGLE_COMPARABLE_ANALYTICAL_SET
            ),
            evidence_use=tuple(no_single_evidence_use),
        )

    support_observation_ids = tuple(
        sorted(
            eligible_ids,
            key=str,
        )
    )
    support_ids = set(support_observation_ids)

    evidence_use: list[MethodEvidenceUse] = []

    for observation in _canonical_considered_observations(
        authoritative_input
    ):
        observation_id = observation.observation_id

        if observation_id in support_ids:
            evidence_use.append(
                MethodEvidenceUse(
                    observation_id=observation_id,
                    role="USED",
                    reason="authoritative_s3_comparable_agreement",
                )
            )
        else:
            evidence_use.append(
                MethodEvidenceUse(
                    observation_id=observation_id,
                    role="EXCLUDED",
                    reason=exclusions[observation_id],
                )
            )

    return AuthoritativeAnalyticalSet(
        configuration=configuration,
        support_view="CURRENT",
        support_observation_ids=support_observation_ids,
        evidence_use=tuple(evidence_use),
    )


def _current_single_stream_support(
    configuration: MethodConfiguration,
    authoritative_input: AuthoritativeMethodInput,
) -> AuthoritativeAnalyticalSet | MethodNoResult | None:
    support_view = _validate_support_configuration(
        configuration,
        authoritative_input,
    )
    if support_view != "CURRENT":
        return None

    eligible, exclusions = _initial_support_population(
        authoritative_input,
        support_view,
    )

    excluded_use = tuple(
        MethodEvidenceUse(
            observation_id=observation_id,
            role="EXCLUDED",
            reason=exclusions[observation_id],
        )
        for observation_id in sorted(
            exclusions,
            key=str,
        )
    )

    if not eligible:
        return MethodNoResult(
            configuration=configuration,
            reason=MethodNoResultReason.NO_ELIGIBLE_CURRENT_EVIDENCE,
            evidence_use=excluded_use,
        )

    stream_identities = {
        _support_stream_identity(observation)
        for observation in eligible
    }
    if len(stream_identities) != 1:
        return None

    support_observation_ids = tuple(
        sorted(
            (
                observation.observation_id
                for observation in eligible
            ),
            key=str,
        )
    )

    support_ids = set(support_observation_ids)
    evidence_use: list[MethodEvidenceUse] = []

    for observation in _canonical_considered_observations(
        authoritative_input
    ):
        observation_id = observation.observation_id

        if observation_id in support_ids:
            evidence_use.append(
                MethodEvidenceUse(
                    observation_id=observation_id,
                    role="USED",
                    reason="authoritative_single_stream_support",
                )
            )
        else:
            evidence_use.append(
                MethodEvidenceUse(
                    observation_id=observation_id,
                    role="EXCLUDED",
                    reason=exclusions[observation_id],
                )
            )

    return AuthoritativeAnalyticalSet(
        configuration=configuration,
        support_view="CURRENT",
        support_observation_ids=support_observation_ids,
        evidence_use=tuple(evidence_use),
    )


def _historical_no_result_evidence_use(
    authoritative_input: AuthoritativeMethodInput,
    exclusions: Mapping[UUID, Name],
    *,
    fallback_reason: Name,
    eligible_reasons: Mapping[UUID, Name] | None = None,
    preserve_unassigned_continuity: bool = False,
) -> tuple[MethodEvidenceUse, ...]:
    unassigned_reasons: dict[UUID, Name] = {}

    if preserve_unassigned_continuity:
        unassigned_reasons = {
            entry.observation_id: (
                f"continuity:{entry.reason.value}:{entry.detail}"
            )
            for entry in authoritative_input.continuity_result.unassigned
        }

    evidence_use: list[MethodEvidenceUse] = []

    for observation in _canonical_considered_observations(
        authoritative_input
    ):
        observation_id = observation.observation_id

        if observation_id in exclusions:
            reason = exclusions[observation_id]
        elif (
            eligible_reasons is not None
            and observation_id in eligible_reasons
        ):
            reason = eligible_reasons[observation_id]
        elif observation_id in unassigned_reasons:
            reason = unassigned_reasons[observation_id]
        else:
            reason = fallback_reason

        evidence_use.append(
            MethodEvidenceUse(
                observation_id=observation_id,
                role="EXCLUDED",
                reason=reason,
            )
        )

    return tuple(evidence_use)


def _historical_support_binding(
    configuration: MethodConfiguration,
    authoritative_input: AuthoritativeMethodInput,
) -> AuthoritativeAnalyticalSet | MethodNoResult | None:
    support_view = _validate_support_configuration(
        configuration,
        authoritative_input,
    )

    if support_view != "HISTORICAL":
        return None

    eligible, exclusions = _initial_support_population(
        authoritative_input,
        support_view,
    )

    considered = _canonical_considered_observations(
        authoritative_input
    )

    if not eligible:
        evidence_use: list[MethodEvidenceUse] = []

        for observation in considered:
            observation_id = observation.observation_id

            if observation_id not in exclusions:
                raise MalformedS3ArtifactError(
                    "historical no-support accounting is incomplete"
                )

            evidence_use.append(
                MethodEvidenceUse(
                    observation_id=observation_id,
                    role="EXCLUDED",
                    reason=exclusions[observation_id],
                )
            )

        return MethodNoResult(
            configuration=configuration,
            reason=(
                MethodNoResultReason
                .NO_ELIGIBLE_HISTORICAL_EVIDENCE
            ),
            evidence_use=tuple(evidence_use),
        )

    eligible_ids = {
        observation.observation_id
        for observation in eligible
    }

    stream_identities = {
        _support_stream_identity(observation)
        for observation in eligible
    }

    full_agreements = 0
    full_conflict_reasons: dict[UUID, set[Name]] = {}

    for binding in authoritative_input.conflict_bindings:
        for agreement in binding.result.agreements:
            if (
                set(agreement.participant_evidence_ids)
                == eligible_ids
            ):
                full_agreements += 1

        for conflict in binding.result.conflicts:
            participant_ids = set(
                conflict.participant_evidence_ids
            )

            if participant_ids != eligible_ids:
                continue

            reason = (
                f"conflict:{conflict.kind.value}:"
                f"{conflict.reason}"
            )

            for observation_id in participant_ids:
                full_conflict_reasons.setdefault(
                    observation_id,
                    set(),
                ).add(reason)

    if full_conflict_reasons:
        canonical_conflict_reasons: dict[UUID, Name] = {}

        for observation_id in eligible_ids:
            reasons = full_conflict_reasons.get(
                observation_id
            )

            if not reasons:
                raise MalformedS3ArtifactError(
                    "full historical conflict accounting "
                    "does not cover every eligible observation"
                )

            canonical_conflict_reasons[observation_id] = min(
                reasons
            )

        return MethodNoResult(
            configuration=configuration,
            reason=MethodNoResultReason.UNRESOLVED_CONFLICT,
            evidence_use=_historical_no_result_evidence_use(
                authoritative_input,
                exclusions,
                fallback_reason=(
                    "method:no_single_comparable_analytical_set"
                ),
                eligible_reasons=canonical_conflict_reasons,
            ),
        )

    if (
        len(stream_identities) > 1
        and full_agreements == 0
    ):
        return MethodNoResult(
            configuration=configuration,
            reason=(
                MethodNoResultReason
                .NO_SINGLE_COMPARABLE_ANALYTICAL_SET
            ),
            evidence_use=_historical_no_result_evidence_use(
                authoritative_input,
                exclusions,
                fallback_reason=(
                    "method:no_single_comparable_analytical_set"
                ),
            ),
        )

    eligible_observation_ids = tuple(
        observation.observation_id
        for observation in eligible
    )

    segment_binding = _historical_segment_binding(
        authoritative_input,
        eligible_observation_ids,
    )

    if segment_binding is None:
        return MethodNoResult(
            configuration=configuration,
            reason=(
                MethodNoResultReason
                .NO_SINGLE_CONTINUITY_SEGMENT
            ),
            evidence_use=_historical_no_result_evidence_use(
                authoritative_input,
                exclusions,
                fallback_reason=(
                    "method:no_single_continuity_segment"
                ),
                preserve_unassigned_continuity=True,
            ),
        )

    segment_id, ordered_support_ids = segment_binding

    evidence_use = [
        MethodEvidenceUse(
            observation_id=observation_id,
            role="USED",
            reason=(
                "authoritative_same_segment_historical_support"
            ),
        )
        for observation_id in ordered_support_ids
    ]

    for observation_id in sorted(
        exclusions,
        key=str,
    ):
        evidence_use.append(
            MethodEvidenceUse(
                observation_id=observation_id,
                role="EXCLUDED",
                reason=exclusions[observation_id],
            )
        )

    return AuthoritativeAnalyticalSet(
        configuration=configuration,
        support_view="HISTORICAL",
        support_observation_ids=ordered_support_ids,
        evidence_use=tuple(evidence_use),
        continuity_segment_id=segment_id,
    )


def bind_method_support(
    *,
    configuration: MethodConfiguration,
    authoritative_input: AuthoritativeMethodInput,
) -> AuthoritativeAnalyticalSet | MethodNoResult:
    """Bind accepted authoritative support without executing method arithmetic."""

    try:
        configuration = MethodConfiguration.model_validate(
            configuration
        )
    except MethodError:
        raise
    except (ValidationError, TypeError, ValueError) as exc:
        raise InvalidMethodConfigurationError(
            "method configuration failed public-boundary revalidation"
        ) from exc

    try:
        authoritative_input = AuthoritativeMethodInput.model_validate(
            authoritative_input
        )
    except MethodError:
        raise
    except (ValidationError, TypeError, ValueError, KeyError) as exc:
        raise MalformedAuthoritativeInputError(
            "authoritative method input failed public-boundary revalidation"
        ) from exc

    support_view = _validate_support_configuration(
        configuration,
        authoritative_input,
    )
    method_name = configuration.semantic_payload.method_name

    if method_name == MethodName.MISSING_FRACTION:
        evidence_use = tuple(
            MethodEvidenceUse(
                observation_id=observation.observation_id,
                role="EXCLUDED",
                reason="method:missing_opportunity_authority",
            )
            for observation in _canonical_considered_observations(
                authoritative_input
            )
        )

        return MethodNoResult(
            configuration=configuration,
            reason=(
                MethodNoResultReason.MISSING_OPPORTUNITY_AUTHORITY
            ),
            evidence_use=evidence_use,
        )

    if support_view == "CURRENT":
        multi_stream = _current_multi_stream_support(
            configuration,
            authoritative_input,
        )
        if multi_stream is not None:
            return multi_stream

        single_stream = _current_single_stream_support(
            configuration,
            authoritative_input,
        )
        if single_stream is not None:
            return single_stream

        raise MalformedS3ArtifactError(
            "current support binding produced no authoritative outcome"
        )

    if support_view == "HISTORICAL":
        historical = _historical_support_binding(
            configuration,
            authoritative_input,
        )
        if historical is not None:
            return historical

        raise MalformedS3ArtifactError(
            "historical support binding produced no authoritative outcome"
        )

    raise UnknownMethodError(
        f"unsupported method identity: {method_name!r}"
    )


class MethodUnitSemantics(_InvariantStateContract):
    """Structured output-unit meaning without conversion or display synthesis."""

    kind: Literal[
        "FIELD_VALUE",
        "COUNTER_QUANTITY_PER_SOURCE_TIME",
        "VALUE_QUANTITY_PER_HISTORICAL_TIME",
        "DIMENSIONLESS",
    ]
    value_unit: str | None = None
    numerator_unit: str | None = None
    denominator_time_basis: Literal["SOURCE_TIME", "HISTORICAL_TIME"] | None = None
    declared_result_unit: str | None = None

    @model_validator(mode="after")
    def components_match_kind(self) -> Self:
        if self.kind == "FIELD_VALUE":
            if not self.value_unit or self.numerator_unit is not None or self.denominator_time_basis is not None:
                raise ValueError("FIELD_VALUE requires only value_unit semantics")
            if self.declared_result_unit is not None and self.declared_result_unit != self.value_unit:
                raise ValueError("FIELD_VALUE cannot claim a different declared result unit")
        elif self.kind == "COUNTER_QUANTITY_PER_SOURCE_TIME":
            if (
                not self.numerator_unit
                or self.denominator_time_basis != "SOURCE_TIME"
                or self.value_unit is not None
            ):
                raise ValueError("counter rate requires counter quantity and SOURCE_TIME semantics")
        elif self.kind == "VALUE_QUANTITY_PER_HISTORICAL_TIME":
            if (
                not self.numerator_unit
                or self.denominator_time_basis != "HISTORICAL_TIME"
                or self.value_unit is not None
            ):
                raise ValueError("historical slope requires value quantity and HISTORICAL_TIME semantics")
        elif any(
            component is not None
            for component in (
                self.value_unit,
                self.numerator_unit,
                self.denominator_time_basis,
                self.declared_result_unit,
            )
        ):
            raise ValueError("DIMENSIONLESS cannot claim unit components")
        return self


class MethodEvidenceUse(_InvariantStateContract):
    """Method-layer use of one observation, with no assessment disposition."""

    observation_id: UUID
    role: Literal["USED", "EXCLUDED"]
    reason: Name


class MethodNoResultReason(StrEnum):
    """Stable ordinary no-result vocabulary; these are not field assessments."""

    NO_ELIGIBLE_CURRENT_EVIDENCE = "NO_ELIGIBLE_CURRENT_EVIDENCE"
    NO_ELIGIBLE_HISTORICAL_EVIDENCE = "NO_ELIGIBLE_HISTORICAL_EVIDENCE"
    INSUFFICIENT_CARDINALITY = "INSUFFICIENT_CARDINALITY"
    NO_SINGLE_COMPARABLE_ANALYTICAL_SET = "NO_SINGLE_COMPARABLE_ANALYTICAL_SET"
    UNRESOLVED_CONFLICT = "UNRESOLVED_CONFLICT"
    AMBIGUOUS_LATEST_TIME = "AMBIGUOUS_LATEST_TIME"
    NO_SINGLE_CONTINUITY_SEGMENT = "NO_SINGLE_CONTINUITY_SEGMENT"
    NO_POSITIVE_ELAPSED_INTERVAL = "NO_POSITIVE_ELAPSED_INTERVAL"
    MISSING_OPPORTUNITY_AUTHORITY = "MISSING_OPPORTUNITY_AUTHORITY"
    RESULT_UNIT_SEMANTICS_UNDECLARED = "RESULT_UNIT_SEMANTICS_UNDECLARED"


def _validate_evidence_accounting(
    evidence_use: tuple[MethodEvidenceUse, ...],
    *,
    permit_used: bool,
) -> None:
    identifiers = [item.observation_id for item in evidence_use]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("duplicate method evidence identity")
    if not permit_used and any(item.role == "USED" for item in evidence_use):
        raise ValueError("a no-result outcome cannot claim used evidence")


class AuthoritativeAnalyticalSet(_InvariantStateContract):
    """Closed authoritative support identity for one later method computation."""

    configuration: MethodConfiguration
    support_view: Literal["CURRENT", "HISTORICAL"]
    support_observation_ids: tuple[UUID, ...] = Field(min_length=1)
    evidence_use: tuple[MethodEvidenceUse, ...] = Field(min_length=1)
    continuity_segment_id: str | None = None
    limitations: tuple[Name, ...] = ()

    @model_validator(mode="after")
    def support_accounting_is_closed(self) -> Self:
        _validate_evidence_accounting(self.evidence_use, permit_used=True)

        expected_view = _support_view_for_method(
            self.configuration.semantic_payload.method_name
        )
        if expected_view is None:
            raise ValueError(
                "missing_fraction cannot claim analytical support without "
                "opportunity authority"
            )
        if self.support_view != expected_view:
            raise ValueError(
                "analytical support view disagrees with the configured method"
            )

        if len(set(self.support_observation_ids)) != len(self.support_observation_ids):
            raise ValueError("duplicate authoritative support observation identity")

        used_ids = tuple(
            item.observation_id
            for item in self.evidence_use
            if item.role == "USED"
        )
        if not used_ids:
            raise ValueError("authoritative analytical set requires used evidence")

        if used_ids != self.support_observation_ids:
            raise ValueError(
                "authoritative analytical set support identity disagrees with evidence use"
            )

        if self.support_view == "CURRENT" and self.continuity_segment_id is not None:
            raise ValueError(
                "current analytical support cannot claim a historical continuity segment"
            )

        if self.support_view == "HISTORICAL" and self.continuity_segment_id is None:
            raise ValueError(
                "historical analytical support requires an authoritative continuity segment"
            )

        return self


class MethodValueResult(_InvariantStateContract):
    """A method-layer value with exact configuration and evidence-use identity."""

    outcome_kind: Literal["VALUE"] = "VALUE"
    configuration: MethodConfiguration
    value: ExactNumber | StrictInt | StrictFloat | StrictStr | StrictBool
    unit_semantics: MethodUnitSemantics
    evidence_use: tuple[MethodEvidenceUse, ...] = Field(min_length=1)
    limitations: tuple[Name, ...] = ()

    @field_validator("value")
    @classmethod
    def scalar_value_is_closed(
        cls,
        value: ExactNumber | int | float | str | bool,
    ) -> ExactNumber | int | float | str | bool:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("method result floats must be finite")
        return value

    @model_validator(mode="after")
    def value_and_evidence_are_consistent(self) -> Self:
        _validate_evidence_accounting(self.evidence_use, permit_used=True)
        if not any(item.role == "USED" for item in self.evidence_use):
            raise ValueError("a value result requires used evidence")
        return self

    @property
    def method_name(self) -> MethodName:
        return self.configuration.semantic_payload.method_name

    @property
    def method_version(self) -> MethodVersion:
        return self.configuration.semantic_payload.method_version

    @property
    def field_contract_id(self) -> str:
        return self.configuration.semantic_payload.field_contract_id

    @property
    def field_contract_version(self) -> str:
        return self.configuration.semantic_payload.field_contract_version

    @property
    def configuration_sha256(self) -> str:
        return self.configuration.configuration_sha256


class MethodNoResult(_InvariantStateContract):
    """An ordinary method-layer no-result with no value or assessment claim."""

    outcome_kind: Literal["NO_RESULT"] = "NO_RESULT"
    configuration: MethodConfiguration
    reason: MethodNoResultReason
    evidence_use: tuple[MethodEvidenceUse, ...] = ()
    limitations: tuple[Name, ...] = ()

    @model_validator(mode="after")
    def evidence_is_not_claimed_as_support(self) -> Self:
        _validate_evidence_accounting(self.evidence_use, permit_used=False)
        return self

    @property
    def method_name(self) -> MethodName:
        return self.configuration.semantic_payload.method_name

    @property
    def method_version(self) -> MethodVersion:
        return self.configuration.semantic_payload.method_version

    @property
    def field_contract_id(self) -> str:
        return self.configuration.semantic_payload.field_contract_id

    @property
    def field_contract_version(self) -> str:
        return self.configuration.semantic_payload.field_contract_version

    @property
    def configuration_sha256(self) -> str:
        return self.configuration.configuration_sha256


type MethodOutcome = Annotated[
    MethodValueResult | MethodNoResult,
    Field(discriminator="outcome_kind"),
]


_R3_CURRENT_EXECUTION_METHODS = frozenset(
    {
        MethodName.LATEST_ELIGIBLE_VALUE,
        MethodName.ARITHMETIC_MEAN,
        MethodName.MEDIAN,
        MethodName.MIN,
        MethodName.MAX,
    }
)

_R3_NOT_LATEST_REASON = "method:not_latest_chronological_point"
_R3_AMBIGUOUS_LATEST_REASON = "method:ambiguous_latest_time"
_R3_UNDECLARED_UNIT_REASON = "method:result_unit_semantics_undeclared"


def _r3_validated_configuration(
    configuration: MethodConfiguration,
) -> MethodConfiguration:
    try:
        return MethodConfiguration.model_validate(configuration)
    except MethodError:
        raise
    except (ValidationError, TypeError, ValueError) as exc:
        raise InvalidMethodConfigurationError(
            "R3 configuration failed execution-boundary revalidation"
        ) from exc


def _r3_validated_authoritative_input(
    authoritative_input: AuthoritativeMethodInput,
) -> AuthoritativeMethodInput:
    try:
        return AuthoritativeMethodInput.model_validate(
            authoritative_input
        )
    except MethodError:
        raise
    except (ValidationError, TypeError, ValueError, KeyError) as exc:
        raise MalformedAuthoritativeInputError(
            "R3 authoritative input failed execution-boundary revalidation"
        ) from exc


def _r3_support_observations(
    analytical_set: AuthoritativeAnalyticalSet,
    authoritative_input: AuthoritativeMethodInput,
) -> tuple[RuntimeObservation, ...]:
    observations = authoritative_input.observations_by_id

    try:
        return tuple(
            observations[observation_id]
            for observation_id in analytical_set.support_observation_ids
        )
    except KeyError as exc:
        raise MalformedS3ArtifactError(
            "R3 analytical support references an unknown observation"
        ) from exc


def _r3_no_result_evidence_use(
    analytical_set: AuthoritativeAnalyticalSet,
    *,
    support_reason: str,
) -> tuple[MethodEvidenceUse, ...]:
    support_ids = set(
        analytical_set.support_observation_ids
    )

    return tuple(
        MethodEvidenceUse(
            observation_id=item.observation_id,
            role="EXCLUDED",
            reason=(
                support_reason
                if item.observation_id in support_ids
                else item.reason
            ),
        )
        for item in analytical_set.evidence_use
    )


def _r3_unit_semantics(
    analytical_set: AuthoritativeAnalyticalSet,
    authoritative_input: AuthoritativeMethodInput,
) -> MethodUnitSemantics | MethodNoResult:
    output_unit = authoritative_input.field_contract.output_unit

    if not output_unit:
        return MethodNoResult(
            configuration=analytical_set.configuration,
            reason=(
                MethodNoResultReason.RESULT_UNIT_SEMANTICS_UNDECLARED
            ),
            evidence_use=_r3_no_result_evidence_use(
                analytical_set,
                support_reason=_R3_UNDECLARED_UNIT_REASON,
            ),
            limitations=analytical_set.limitations,
        )

    return MethodUnitSemantics(
        kind="FIELD_VALUE",
        value_unit=output_unit,
        declared_result_unit=output_unit,
    )


def _r3_exact_fraction(value: object) -> Fraction:
    if isinstance(value, bool):
        raise UnsupportedValueKindError(
            "boolean evidence is not numeric"
        )

    if isinstance(value, int):
        return Fraction(value, 1)

    if isinstance(value, float):
        if not math.isfinite(value):
            raise UnsupportedValueKindError(
                "numeric evidence must be finite"
            )

        numerator, denominator = value.as_integer_ratio()
        return Fraction(numerator, denominator)

    raise UnsupportedValueKindError(
        "R3 aggregate methods require numeric evidence"
    )


def _r3_exact_number(value: Fraction) -> ExactNumber:
    return ExactNumber.from_ratio(
        value.numerator,
        value.denominator,
    )


def _r3_latest_scalar(
    value: object,
) -> int | float | str | bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise UnsupportedValueKindError(
                "latest numeric evidence must be finite"
            )
        return value

    if isinstance(value, str):
        return value

    raise UnsupportedValueKindError(
        "latest supports only number, string, or boolean scalars"
    )


def _r3_latest_evidence_use(
    analytical_set: AuthoritativeAnalyticalSet,
    selected_id: UUID,
) -> tuple[MethodEvidenceUse, ...]:
    support_ids = set(
        analytical_set.support_observation_ids
    )

    selected_seen = False
    result: list[MethodEvidenceUse] = []

    for item in analytical_set.evidence_use:
        if item.observation_id == selected_id:
            if item.observation_id not in support_ids:
                raise MalformedS3ArtifactError(
                    "latest selected observation is not authoritative support"
                )

            if item.role != "USED":
                raise MalformedS3ArtifactError(
                    "latest selected support is not marked USED"
                )

            selected_seen = True
            result.append(item)
            continue

        if item.observation_id in support_ids:
            result.append(
                MethodEvidenceUse(
                    observation_id=item.observation_id,
                    role="EXCLUDED",
                    reason=_R3_NOT_LATEST_REASON,
                )
            )
            continue

        result.append(item)

    if not selected_seen:
        raise MalformedS3ArtifactError(
            "latest selected observation is absent from evidence accounting"
        )

    return tuple(result)


def _r3_execute_latest(
    analytical_set: AuthoritativeAnalyticalSet,
    authoritative_input: AuthoritativeMethodInput,
    unit_semantics: MethodUnitSemantics,
) -> MethodOutcome:
    observations = _r3_support_observations(
        analytical_set,
        authoritative_input,
    )

    basis = authoritative_input.field_contract.temporal_basis

    timed: list[tuple[datetime, RuntimeObservation]] = []

    for observation in observations:
        selected_time = _selected_time(
            observation,
            basis,
        )

        if selected_time is None:
            raise MalformedS3ArtifactError(
                "latest authoritative support lacks its selected clock"
            )

        timed.append(
            (
                selected_time,
                observation,
            )
        )

    latest_time = max(
        selected_time
        for selected_time, _ in timed
    )

    winners = tuple(
        observation
        for selected_time, observation in timed
        if selected_time == latest_time
    )

    if len(winners) != 1:
        return MethodNoResult(
            configuration=analytical_set.configuration,
            reason=MethodNoResultReason.AMBIGUOUS_LATEST_TIME,
            evidence_use=_r3_no_result_evidence_use(
                analytical_set,
                support_reason=_R3_AMBIGUOUS_LATEST_REASON,
            ),
            limitations=analytical_set.limitations,
        )

    winner = winners[0]

    return MethodValueResult(
        configuration=analytical_set.configuration,
        value=_r3_latest_scalar(winner.value),
        unit_semantics=unit_semantics,
        evidence_use=_r3_latest_evidence_use(
            analytical_set,
            winner.observation_id,
        ),
        limitations=analytical_set.limitations,
    )


def _r3_execute_aggregate(
    method_name: MethodName,
    analytical_set: AuthoritativeAnalyticalSet,
    authoritative_input: AuthoritativeMethodInput,
    unit_semantics: MethodUnitSemantics,
) -> MethodValueResult:
    observations = _r3_support_observations(
        analytical_set,
        authoritative_input,
    )

    values = tuple(
        _r3_exact_fraction(observation.value)
        for observation in observations
    )

    if not values:
        raise DeterministicArithmeticError(
            "R3 aggregate received empty authoritative support"
        )

    if method_name == MethodName.ARITHMETIC_MEAN:
        total = Fraction(0, 1)

        for value in values:
            total += value

        result_value = total / len(values)

    elif method_name == MethodName.MEDIAN:
        ordered = sorted(values)
        count = len(ordered)
        midpoint = count // 2

        if count % 2:
            result_value = ordered[midpoint]
        else:
            result_value = (
                ordered[midpoint - 1]
                + ordered[midpoint]
            ) / 2

    elif method_name == MethodName.MIN:
        result_value = min(values)

    elif method_name == MethodName.MAX:
        result_value = max(values)

    else:
        raise MethodOperationError(
            f"method is outside the R3 aggregate set: {method_name!r}"
        )

    return MethodValueResult(
        configuration=analytical_set.configuration,
        value=_r3_exact_number(result_value),
        unit_semantics=unit_semantics,
        evidence_use=analytical_set.evidence_use,
        limitations=analytical_set.limitations,
    )


def _execute_r3_method(
    *,
    configuration: MethodConfiguration,
    authoritative_input: AuthoritativeMethodInput,
) -> MethodOutcome:
    """Execute one private R3 current method from authoritative inputs only."""

    validated_configuration = _r3_validated_configuration(
        configuration
    )

    method_name = (
        validated_configuration
        .semantic_payload
        .method_name
    )

    if method_name not in _R3_CURRENT_EXECUTION_METHODS:
        raise MethodOperationError(
            f"method is outside the private R3 execution scope: {method_name.value}"
        )

    validated_input = _r3_validated_authoritative_input(
        authoritative_input
    )

    bound = bind_method_support(
        configuration=validated_configuration,
        authoritative_input=validated_input,
    )

    if isinstance(bound, MethodNoResult):
        return bound

    if bound.support_view != "CURRENT":
        raise MethodOperationError(
            "R3 current execution received historical analytical support"
        )

    unit_semantics = _r3_unit_semantics(
        bound,
        validated_input,
    )

    if isinstance(unit_semantics, MethodNoResult):
        return unit_semantics

    if method_name == MethodName.LATEST_ELIGIBLE_VALUE:
        return _r3_execute_latest(
            bound,
            validated_input,
            unit_semantics,
        )

    return _r3_execute_aggregate(
        method_name,
        bound,
        validated_input,
        unit_semantics,
    )


# ---------------------------------------------------------------------------
# S4A-R4 ? exact historical endpoint arithmetic
# ---------------------------------------------------------------------------


_R4_HISTORICAL_EXECUTION_METHODS = frozenset(
    {
        MethodName.WITHIN_SEGMENT_DELTA,
        MethodName.SOURCE_TIME_COUNTER_RATE,
        MethodName.HISTORICAL_ENDPOINT_SLOPE,
    }
)

_R4_INSUFFICIENT_CARDINALITY_REASON = (
    "method:insufficient_cardinality"
)

_R4_NO_POSITIVE_ELAPSED_REASON = (
    "method:no_positive_elapsed_interval"
)

_R4_UNDECLARED_UNIT_REASON = (
    "method:result_unit_semantics_undeclared"
)


def _r4_validated_configuration(
    configuration: MethodConfiguration,
) -> MethodConfiguration:
    try:
        return MethodConfiguration.model_validate(
            configuration
        )
    except MethodError:
        raise
    except (
        ValidationError,
        TypeError,
        ValueError,
    ) as exc:
        raise InvalidMethodConfigurationError(
            "R4 configuration failed execution-boundary revalidation"
        ) from exc


def _r4_validated_authoritative_input(
    authoritative_input: AuthoritativeMethodInput,
) -> AuthoritativeMethodInput:
    try:
        return AuthoritativeMethodInput.model_validate(
            authoritative_input
        )
    except MethodError:
        raise
    except (
        ValidationError,
        TypeError,
        ValueError,
        KeyError,
    ) as exc:
        raise MalformedAuthoritativeInputError(
            "R4 authoritative input failed execution-boundary "
            "revalidation"
        ) from exc


def _r4_support_observations(
    analytical_set: AuthoritativeAnalyticalSet,
    authoritative_input: AuthoritativeMethodInput,
) -> tuple[RuntimeObservation, ...]:
    observations = (
        authoritative_input.observations_by_id
    )

    try:
        return tuple(
            observations[observation_id]
            for observation_id
            in analytical_set.support_observation_ids
        )
    except KeyError as exc:
        raise MalformedS3ArtifactError(
            "R4 analytical support references an unknown observation"
        ) from exc


def _r4_no_result_evidence_use(
    analytical_set: AuthoritativeAnalyticalSet,
    *,
    support_reason: str,
) -> tuple[MethodEvidenceUse, ...]:
    support_ids = set(
        analytical_set.support_observation_ids
    )

    return tuple(
        MethodEvidenceUse(
            observation_id=item.observation_id,
            role="EXCLUDED",
            reason=(
                support_reason
                if item.observation_id
                in support_ids
                else item.reason
            ),
        )
        for item in analytical_set.evidence_use
    )


def _r4_no_result(
    analytical_set: AuthoritativeAnalyticalSet,
    *,
    reason: MethodNoResultReason,
    support_reason: str,
) -> MethodNoResult:
    return MethodNoResult(
        configuration=analytical_set.configuration,
        reason=reason,
        evidence_use=_r4_no_result_evidence_use(
            analytical_set,
            support_reason=support_reason,
        ),
        limitations=analytical_set.limitations,
    )


def _r4_exact_fraction(
    value: object,
) -> Fraction:
    if isinstance(value, bool):
        raise UnsupportedValueKindError(
            "boolean evidence is not numeric"
        )

    if isinstance(value, int):
        return Fraction(
            value,
            1,
        )

    if isinstance(value, float):
        if not math.isfinite(value):
            raise UnsupportedValueKindError(
                "R4 numeric evidence must be finite"
            )

        numerator, denominator = (
            value.as_integer_ratio()
        )

        return Fraction(
            numerator,
            denominator,
        )

    raise UnsupportedValueKindError(
        "R4 historical arithmetic requires numeric evidence"
    )


def _r4_exact_number(
    value: Fraction,
) -> ExactNumber:
    return ExactNumber.from_ratio(
        value.numerator,
        value.denominator,
    )


def _r4_exact_elapsed_seconds(
    first: datetime | None,
    last: datetime | None,
) -> Fraction | None:
    if first is None or last is None:
        return None

    elapsed = last - first

    total_microseconds = (
        elapsed.days
        * 86_400
        * 1_000_000
        + elapsed.seconds
        * 1_000_000
        + elapsed.microseconds
    )

    if total_microseconds <= 0:
        return None

    return Fraction(
        total_microseconds,
        1_000_000,
    )


def _r4_unit_semantics(
    method_name: MethodName,
    analytical_set: AuthoritativeAnalyticalSet,
    authoritative_input: AuthoritativeMethodInput,
) -> MethodUnitSemantics | MethodNoResult:
    output_unit = (
        authoritative_input
        .field_contract
        .output_unit
    )

    if not output_unit:
        return _r4_no_result(
            analytical_set,
            reason=(
                MethodNoResultReason
                .RESULT_UNIT_SEMANTICS_UNDECLARED
            ),
            support_reason=(
                _R4_UNDECLARED_UNIT_REASON
            ),
        )

    if (
        method_name
        == MethodName.WITHIN_SEGMENT_DELTA
    ):
        return MethodUnitSemantics(
            kind="FIELD_VALUE",
            value_unit=output_unit,
            declared_result_unit=output_unit,
        )

    if (
        method_name
        == MethodName.SOURCE_TIME_COUNTER_RATE
    ):
        return MethodUnitSemantics(
            kind=(
                "COUNTER_QUANTITY_PER_SOURCE_TIME"
            ),
            numerator_unit=output_unit,
            denominator_time_basis="SOURCE_TIME",
        )

    if (
        method_name
        == MethodName.HISTORICAL_ENDPOINT_SLOPE
    ):
        return MethodUnitSemantics(
            kind=(
                "VALUE_QUANTITY_PER_HISTORICAL_TIME"
            ),
            numerator_unit=output_unit,
            denominator_time_basis="HISTORICAL_TIME",
        )

    raise MethodOperationError(
        "method is outside the R4 unit-semantic scope"
    )


def _r4_endpoint_delta(
    observations: tuple[
        RuntimeObservation,
        ...,
    ],
) -> Fraction:
    first = observations[0]
    last = observations[-1]

    return (
        _r4_exact_fraction(last.value)
        - _r4_exact_fraction(first.value)
    )


def _r4_execute_delta(
    analytical_set: AuthoritativeAnalyticalSet,
    observations: tuple[
        RuntimeObservation,
        ...,
    ],
    unit_semantics: MethodUnitSemantics,
) -> MethodValueResult:
    delta = _r4_endpoint_delta(
        observations
    )

    return MethodValueResult(
        configuration=analytical_set.configuration,
        value=_r4_exact_number(delta),
        unit_semantics=unit_semantics,
        evidence_use=analytical_set.evidence_use,
        limitations=analytical_set.limitations,
    )


def _r4_execute_source_time_rate(
    analytical_set: AuthoritativeAnalyticalSet,
    observations: tuple[
        RuntimeObservation,
        ...,
    ],
    unit_semantics: MethodUnitSemantics,
) -> MethodOutcome:
    first = observations[0]
    last = observations[-1]

    elapsed = _r4_exact_elapsed_seconds(
        first.observation_time,
        last.observation_time,
    )

    if elapsed is None:
        return _r4_no_result(
            analytical_set,
            reason=(
                MethodNoResultReason
                .NO_POSITIVE_ELAPSED_INTERVAL
            ),
            support_reason=(
                _R4_NO_POSITIVE_ELAPSED_REASON
            ),
        )

    result_value = (
        _r4_endpoint_delta(observations)
        / elapsed
    )

    return MethodValueResult(
        configuration=analytical_set.configuration,
        value=_r4_exact_number(
            result_value
        ),
        unit_semantics=unit_semantics,
        evidence_use=analytical_set.evidence_use,
        limitations=analytical_set.limitations,
    )


def _r4_execute_historical_slope(
    analytical_set: AuthoritativeAnalyticalSet,
    authoritative_input: AuthoritativeMethodInput,
    observations: tuple[
        RuntimeObservation,
        ...,
    ],
    unit_semantics: MethodUnitSemantics,
) -> MethodOutcome:
    first = observations[0]
    last = observations[-1]

    basis = (
        authoritative_input
        .field_contract
        .temporal_basis
    )

    first_time = _selected_time(
        first,
        basis,
    )

    last_time = _selected_time(
        last,
        basis,
    )

    elapsed = _r4_exact_elapsed_seconds(
        first_time,
        last_time,
    )

    if elapsed is None:
        return _r4_no_result(
            analytical_set,
            reason=(
                MethodNoResultReason
                .NO_POSITIVE_ELAPSED_INTERVAL
            ),
            support_reason=(
                _R4_NO_POSITIVE_ELAPSED_REASON
            ),
        )

    result_value = (
        _r4_endpoint_delta(observations)
        / elapsed
    )

    return MethodValueResult(
        configuration=analytical_set.configuration,
        value=_r4_exact_number(
            result_value
        ),
        unit_semantics=unit_semantics,
        evidence_use=analytical_set.evidence_use,
        limitations=analytical_set.limitations,
    )


def _execute_r4_method(
    *,
    configuration: MethodConfiguration,
    authoritative_input: AuthoritativeMethodInput,
) -> MethodOutcome:
    """Execute one private R4 historical method."""

    validated_configuration = (
        _r4_validated_configuration(
            configuration
        )
    )

    method_name = (
        validated_configuration
        .semantic_payload
        .method_name
    )

    if (
        method_name
        not in _R4_HISTORICAL_EXECUTION_METHODS
    ):
        raise MethodOperationError(
            "method is outside the private R4 "
            f"execution scope: {method_name.value}"
        )

    validated_input = (
        _r4_validated_authoritative_input(
            authoritative_input
        )
    )

    bound = bind_method_support(
        configuration=validated_configuration,
        authoritative_input=validated_input,
    )

    if isinstance(
        bound,
        MethodNoResult,
    ):
        return bound

    if bound.support_view != "HISTORICAL":
        raise MethodOperationError(
            "R4 historical execution received "
            "non-historical analytical support"
        )

    if bound.continuity_segment_id is None:
        raise MalformedS3ArtifactError(
            "R4 historical analytical support "
            "lacks authoritative continuity identity"
        )

    observations = _r4_support_observations(
        bound,
        validated_input,
    )

    if len(observations) < 2:
        return _r4_no_result(
            bound,
            reason=(
                MethodNoResultReason
                .INSUFFICIENT_CARDINALITY
            ),
            support_reason=(
                _R4_INSUFFICIENT_CARDINALITY_REASON
            ),
        )

    unit_semantics = _r4_unit_semantics(
        method_name,
        bound,
        validated_input,
    )

    if isinstance(
        unit_semantics,
        MethodNoResult,
    ):
        return unit_semantics

    if (
        method_name
        == MethodName.WITHIN_SEGMENT_DELTA
    ):
        return _r4_execute_delta(
            bound,
            observations,
            unit_semantics,
        )

    if (
        method_name
        == MethodName.SOURCE_TIME_COUNTER_RATE
    ):
        return _r4_execute_source_time_rate(
            bound,
            observations,
            unit_semantics,
        )

    if (
        method_name
        == MethodName.HISTORICAL_ENDPOINT_SLOPE
    ):
        return _r4_execute_historical_slope(
            bound,
            validated_input,
            observations,
            unit_semantics,
        )

    raise MethodOperationError(
        "R4 execution reached an impossible method dispatch"
    )
