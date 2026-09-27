"""M3.2-S4-A generic deterministic descriptive method layer.

This module owns generic descriptive method algorithms and their immutable,
digest-addressed configuration. It answers one question for one declared scope:

    given eligible, already-admitted, already-segmented S3 evidence, what is the
    descriptively defensible value produced by exactly the named method?

Boundaries that are deliberately *not* owned here:

* temporal admission, identity resolution, segmentation and conflict detection
  (frozen M3.2-S3 results are consumed as inputs and are never re-derived);
* final field validity (``VALID``/``DEGRADED``/``UNKNOWN``/``INVALID``), which
  belongs to the later ``assessment`` sub-slice;
* snapshot assembly, provenance/content identity, production metadata,
  persistence, provider acquisition, economics, prediction and control.

Method selection is caller-declared. There is no default estimator, no mutable
"latest" alias, no implicit version upgrade and no fallback method: an
unsupported method name or version surfaces as an explicit typed failure.

Determinism: for fixed semantic inputs the semantic method result is fixed.
Nothing here reads the wall clock, generates random identifiers, hashes objects
with ``hash()``, consults the filesystem, a database, a provider, a mutable
global registry or a process-local cache. Unordered methods are input-order
independent (the mean uses exact ``math.fsum`` summation) and every collection
is emitted in an explicit canonical order.

Non-finite rule: no method may produce ``NaN``, ``+Inf`` or ``-Inf``. A
non-finite intermediate or result is rejected with an explicit typed failure; it
is never coerced, clamped or replaced by zero.

Units: an incompatible unit without a declared conversion can never support a
method. Evidence units must match the declared scope unit exactly; no implicit
conversion is performed and this sub-slice implements no conversion arithmetic
(frozen authority declares conversion *names* only), so a declared explicit
versioned conversion establishes declared compatibility only and transforms no
values. A declared conversion never bypasses admission, identity, continuity,
minimum evidence or method validity.
"""

import hashlib
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from json import dumps
from types import MappingProxyType
from typing import Self, cast
from uuid import UUID

from pydantic import Field, ValidationError, model_validator

from mining_guardian.observability.models import RuntimeObservation, Source
from mining_guardian.state.admission import AdmissionAssessment, AdmissionOutcome
from mining_guardian.state.contracts import (
    FrozenMapping,
    FrozenValue,
    Name,
    Sha256,
    StateContract,
    TimeBasis,
)
from mining_guardian.state.subjects import IdentityResolution

METHOD_FAMILY = "m3.2.descriptive-methods"
METHOD_FAMILY_VERSION = "v1"


# Standing limitations. Each is a fact about what a descriptive method does not
# establish; none of them is a validity decision.
CURRENTNESS_LIMITATION = (
    "latest_eligible_value_reports_the_most_recent_eligible_observation_and_"
    "does_not_establish_physical_currentness"
)
RECEIPT_ORDERING_LIMITATION = (
    "receipt_basis_ordering_does_not_establish_source_measurement_order"
)
RECEIPT_ELAPSED_LIMITATION = (
    "receipt_basis_elapsed_time_is_not_source_measurement_time"
)
COUNTER_SCOPE_LIMITATION = (
    "observed_source_counter_change_per_unit_time_requires_a_source_counter_scope_"
    "to_represent_credited_work"
)
SLOPE_DESCRIPTIVE_LIMITATION = (
    "historical_endpoint_slope_is_a_descriptive_historical_quantity_and_not_prediction"
)
MISSING_FRACTION_LIMITATION = (
    "observed_opportunity_count_does_not_reveal_completely_absent_acquisitions"
)
CONVERSION_ROOT_LIMITATION = (
    "declared_unit_conversion_establishes_declared_compatibility_only_and_transforms_"
    "no_values_in_this_slice"
)
IDENTITY_VIOLATION_LIMITATION = (
    "positive_identity_integrity_violation_is_retained_for_downstream_field_consequence"
)
SELECTION_TIE_LIMITATION = (
    "selection_tie_broken_deterministically_by_receipt_time_then_observation_id"
)

# Explicit exclusion reason codes. Every supplied evidence item is accounted for
# exactly once, either as a method participant or as one of these exclusions.
NON_COMPARABLE_REASON = "evidence_marked_non_comparable_by_identity_reconciliation"
IDENTITY_VIOLATION_REASON = "evidence_carries_positive_identity_integrity_violation"
ADMISSION_EXCLUDED_REASON = "admission_outcome_excluded_is_never_method_support"
ADMISSION_CONTEXT_REASON = "admission_outcome_context_only_is_not_current_value_support"
UNRESOLVED_IDENTITY_REASON = "declared_identity_component_unresolved"
STREAM_SCOPE_REASON = "outside_declared_stream_scope"
UNIT_MISMATCH_REASON = "incompatible_unit_without_declared_conversion"
UNIT_MISMATCH_DECLARED_CONVERSION_REASON = (
    "incompatible_unit_declared_conversion_not_applied_in_this_slice"
)
VALUE_MISSING_REASON = "value_missing_not_zero"
SOURCE_TIME_MISSING_REASON = "source_measurement_time_unavailable_for_counter_rate"
UNORDERABLE_REASON = "unorderable_in_declared_ordering_basis"
OUTSIDE_SEGMENT_REASON = "outside_declared_segment_scope"
UNASSIGNED_SEGMENT_REASON = "not_assigned_to_an_analytical_segment"
NOT_LATEST_REASON = "not_the_latest_eligible_observation"
TIED_LATEST_REASON = "tied_latest_ordering_time_not_selected"
NOT_AN_ENDPOINT_REASON = "in_scope_but_not_consumed_by_endpoint_arithmetic"


class MethodError(RuntimeError):
    """Base class for explicit descriptive-method failures."""


class MethodIntegrityError(MethodError):
    """Supplied evidence or scope is not a canonical, unambiguous method input."""


class MethodLimitError(MethodError):
    """A declared bounded-work ceiling was exceeded."""


class UnsupportedMethodError(MethodError):
    """The requested method name is not an authorized generic method."""


class UnsupportedMethodVersionError(MethodError):
    """The requested method version is not supported by this implementation."""


class MethodConfigurationError(MethodError):
    """The method configuration is invalid, incomplete or internally inconsistent."""


class MethodPreconditionError(MethodError):
    """The mathematical preconditions of the named method are not met."""


class CrossSegmentArithmeticError(MethodError):
    """Within-segment arithmetic was requested across an analytical segment boundary."""


class SourceTimeIntervalError(MethodError):
    """An interval used by the method is absent, non-positive or otherwise invalid.

    The primary case is a source-time interval: receipt or ingestion time never
    substitutes for source measurement time, and elapsed time must be strictly
    positive.
    """


class NonFiniteError(MethodError):
    """A non-finite value or result was encountered; it is never coerced or clamped."""


class NonNumericEvidenceError(MethodError):
    """A numeric method received evidence that is not a finite numeric value."""


class MethodName(StrEnum):
    """Authorized generic descriptive methods; exact string identity, no aliases."""

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
    """Explicitly supported method versions; unknown versions fail, none upgrade."""

    V1 = "v1"


class EvidenceComparability(StrEnum):
    """Caller-supplied S3 reconciliation outcome; S4-A never re-derives it.

    ``COMPARABLE`` evidence may support a method. ``NON_COMPARABLE`` evidence
    (ordinary identity mismatch or non-comparability) and ``IDENTITY_VIOLATION``
    evidence (a positive identity-integrity violation) are both excluded from
    method support but stay distinct, so the A/B/C reconciliation cases are never
    collapsed.
    """

    COMPARABLE = "COMPARABLE"
    NON_COMPARABLE = "NON_COMPARABLE"
    IDENTITY_VIOLATION = "IDENTITY_VIOLATION"


class DeclaredConversion(StateContract):
    """Explicit, versioned unit-compatibility declaration.

    Frozen authority declares conversion *names* only; it provides no conversion
    implementation and this sub-slice is not authorized to invent conversion
    arithmetic. S4-A therefore validates and retains the declaration, records
    that declared compatibility was used as a reason code, and transforms no
    values. Evidence in a declared source unit is still never aggregated with
    values expressed in another unit.
    """

    conversion_id: Name
    conversion_version: Name
    source_unit: Name
    target_unit: Name

    @model_validator(mode="after")
    def distinct_units(self) -> Self:
        if self.source_unit == self.target_unit:
            raise ValueError("a declared conversion must name distinct units")
        return self


class _MethodParameterSpec(StateContract):
    """Declared parameter surface of one generic method; no hidden parameters."""

    required: tuple[Name, ...] = ()
    allowed: tuple[Name, ...] = ()


_ALL_VALUE_METHODS = frozenset({
    MethodName.LATEST_ELIGIBLE_VALUE,
    MethodName.ARITHMETIC_MEAN,
    MethodName.MEDIAN,
    MethodName.MIN,
    MethodName.MAX,
    MethodName.WITHIN_SEGMENT_DELTA,
    MethodName.SOURCE_TIME_COUNTER_RATE,
    MethodName.HISTORICAL_ENDPOINT_SLOPE,
})
_NUMERIC_METHODS = _ALL_VALUE_METHODS
_UNIT_CHECKED_METHODS = _ALL_VALUE_METHODS
_ORDERED_METHODS = frozenset({
    MethodName.LATEST_ELIGIBLE_VALUE,
    MethodName.WITHIN_SEGMENT_DELTA,
    MethodName.SOURCE_TIME_COUNTER_RATE,
    MethodName.HISTORICAL_ENDPOINT_SLOPE,
})
_SEGMENT_SCOPED_METHODS = frozenset({
    MethodName.WITHIN_SEGMENT_DELTA,
    MethodName.SOURCE_TIME_COUNTER_RATE,
    MethodName.HISTORICAL_ENDPOINT_SLOPE,
})

# Immutable module-level specifications: never mutated, never extended at
# runtime, no process-local cache authority.
_PARAMETER_SPECS: Mapping[MethodName, _MethodParameterSpec] = MappingProxyType({
    **{name: _MethodParameterSpec(allowed=("declared_conversion",))
       for name in _ALL_VALUE_METHODS},
    MethodName.MISSING_FRACTION: _MethodParameterSpec(
        required=("expected_opportunities",), allowed=("expected_opportunities",)),
})
_SUPPORTED_VERSIONS: Mapping[MethodName, frozenset[MethodVersion]] = MappingProxyType({
    name: frozenset({MethodVersion.V1}) for name in MethodName
})


def supported_method_versions() -> Mapping[MethodName, frozenset[MethodVersion]]:
    """Read-only view of the authorized method/version surface (no mutable registry)."""
    return _SUPPORTED_VERSIONS


def _json_ready(value: object) -> object:
    """Canonical JSON projection of a configuration value; order is not semantic."""
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def method_configuration_digest(*, method_name: str, method_version: str,
                                field_contract_id: str, field_contract_version: str,
                                configuration: Mapping[str, object]) -> str:
    """Deterministic SHA-256 identity of one exact method configuration.

    Canonical serialization: sorted keys, no insignificant whitespace, ASCII
    escaping and no non-finite numbers. Mapping order and equivalent container
    types therefore never change the digest, while any semantic change does.
    """
    payload = dumps(
        {
            "method_family": METHOD_FAMILY,
            "method_family_version": METHOD_FAMILY_VERSION,
            "method_name": method_name,
            "method_version": method_version,
            "field_contract_id": field_contract_id,
            "field_contract_version": field_contract_version,
            "configuration": _json_ready(configuration),
        },
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _resolve_method_name(method_name: object) -> MethodName:
    """Exact-name dispatch; unsupported names fail explicitly and are never remapped."""
    if isinstance(method_name, str):
        try:
            return MethodName(method_name)
        except ValueError as exc:
            raise UnsupportedMethodError(f"unsupported method name: {method_name!r}") from exc
    raise UnsupportedMethodError(f"unsupported method name: {method_name!r}")


def _resolve_method_version(method_name: MethodName, method_version: object) -> MethodVersion:
    """Exact-version dispatch; no implicit upgrade and no 'latest' alias."""
    if isinstance(method_version, str):
        try:
            version = MethodVersion(method_version)
        except ValueError as exc:
            raise UnsupportedMethodVersionError(
                f"unsupported method version: {method_version!r}") from exc
        if version in _SUPPORTED_VERSIONS[method_name]:
            return version
    raise UnsupportedMethodVersionError(
        f"method {method_name.value} does not support version {method_version!r}")


def _validated_parameters(method_name: MethodName,
                          configuration: Mapping[str, object]) -> dict[str, object]:
    """Validate the exact declared parameter surface; there is no default value."""
    spec = _PARAMETER_SPECS[method_name]
    if not isinstance(configuration, Mapping):
        raise MethodConfigurationError("method configuration must be an explicit mapping")
    undeclared = sorted(str(key) for key in configuration if key not in spec.allowed)
    if undeclared:
        raise MethodConfigurationError(
            "undeclared method-configuration parameter: " + ",".join(undeclared))
    missing = [key for key in spec.required if key not in configuration]
    if missing:
        raise MethodConfigurationError(
            "missing mandatory method-configuration parameter: " + ",".join(missing))
    validated: dict[str, object] = {}
    for key in sorted(configuration):
        value = configuration[key]
        if key == "expected_opportunities":
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise MethodConfigurationError(
                    "expected_opportunities must be an explicit positive integer")
            validated[key] = value
        elif key == "declared_conversion":
            try:
                conversion = DeclaredConversion.model_validate(value)
            except (AttributeError, TypeError, ValueError) as exc:
                raise MethodConfigurationError(
                    "the declared conversion declaration is invalid") from exc
            validated[key] = {
                "conversion_id": conversion.conversion_id,
                "conversion_version": conversion.conversion_version,
                "source_unit": conversion.source_unit,
                "target_unit": conversion.target_unit,
            }
        else:  # pragma: no cover - unreachable: the allowlist above rejects it first
            raise MethodConfigurationError(
                f"undeclared method-configuration parameter: {key}")
    return validated


class MethodConfiguration(StateContract):
    """Immutable, digest-addressed configuration of exactly one generic method.

    The exact configuration is retained, never digested away: ``configuration``
    carries every method-specific semantic parameter and ``configuration_sha256``
    is recomputed and re-verified on every construction, so a configuration whose
    digest does not match its content cannot exist. The semantic configuration is
    frozen after validation and cannot be mutated by the caller.

    Requirements that already come authoritatively from ``FieldEvidenceContract``
    (windows, minimum samples, minimum span, coverage, continuity/conflict rules,
    conversion names, resource ceilings) are not restated here.
    """

    method_name: Name
    method_version: Name
    configuration: FrozenMapping[str, FrozenValue]
    configuration_sha256: Sha256
    field_contract_id: Name
    field_contract_version: Name

    @model_validator(mode="after")
    def digest_matches_configuration(self) -> Self:
        try:
            expected = method_configuration_digest(
                method_name=self.method_name,
                method_version=self.method_version,
                field_contract_id=self.field_contract_id,
                field_contract_version=self.field_contract_version,
                configuration=self.configuration,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("method configuration is not canonically serializable") from exc
        if self.configuration_sha256.lower() != expected:
            raise ValueError("method configuration digest does not match its configuration")
        return self

    @classmethod
    def create(cls, *, method_name: str, method_version: str, field_contract_id: str,
               field_contract_version: str,
               configuration: Mapping[str, object]) -> "MethodConfiguration":
        """Validate and seal one configuration; every mandatory field is explicit."""
        resolved_name = _resolve_method_name(method_name)
        resolved_version = _resolve_method_version(resolved_name, method_version)
        parameters = _validated_parameters(resolved_name, configuration)
        try:
            digest = method_configuration_digest(
                method_name=resolved_name.value,
                method_version=resolved_version.value,
                field_contract_id=field_contract_id,
                field_contract_version=field_contract_version,
                configuration=parameters,
            )
            return cls(
                method_name=resolved_name.value,
                method_version=resolved_version.value,
                configuration=cast("Mapping[str, FrozenValue]", parameters),
                configuration_sha256=digest,
                field_contract_id=field_contract_id,
                field_contract_version=field_contract_version,
            )
        except ValidationError as exc:
            raise MethodConfigurationError("invalid method configuration") from exc
        except (TypeError, ValueError) as exc:
            raise MethodConfigurationError("method configuration is not serializable") from exc

    def resolved(self) -> tuple[MethodName, MethodVersion]:
        """Dispatch identity of this configuration, re-resolved explicitly."""
        name = _resolve_method_name(self.method_name)
        return name, _resolve_method_version(name, self.method_version)


class _MethodParameters(StateContract):
    """Validated semantic parameters of one method execution."""

    expected_opportunities: int | None = None
    declared_conversion: DeclaredConversion | None = None


def _resolve_parameters(method_name: MethodName,
                        configuration: MethodConfiguration) -> _MethodParameters:
    """Re-validate the declared parameters of an existing configuration."""
    validated = _validated_parameters(method_name, configuration.configuration)
    conversion = validated.get("declared_conversion")
    return _MethodParameters(
        expected_opportunities=cast("int | None", validated.get("expected_opportunities")),
        declared_conversion=(DeclaredConversion.model_validate(conversion)
                             if conversion is not None else None),
    )


class MethodScope(StateContract):
    """Caller-declared descriptive scope: exactly one source stream and one unit.

    There is no cross-source resolution policy here: a method only ever sees the
    declared stream, and the declared unit is matched exactly.
    """

    source: Source
    source_instance: str | None = Field(default=None, min_length=1)
    signal: Name
    unit: str | None = Field(default=None, min_length=1)

    @property
    def stream_key(self) -> tuple[str, str, str]:
        return (self.source.value, self.source_instance or "", self.signal)


class MethodEvidence(StateContract):
    """One already-admitted, already-identified, already-segmented observation.

    The S3 results are consumed exactly as supplied: eligibility is read from the
    frozen admission outcome, identity from the frozen identity resolution and
    segment membership from the frozen continuity result. S4-A never re-admits
    evidence, repairs identity, merges segments or resolves conflicts.
    """

    record: RuntimeObservation
    admission: AdmissionAssessment
    identity: IdentityResolution
    segment_id: str | None = Field(default=None, min_length=1)
    comparability: EvidenceComparability = EvidenceComparability.COMPARABLE
    comparability_reason: Name | None = None

    @property
    def observation_id(self) -> UUID:
        return self.record.observation_id

    @property
    def stream_key(self) -> tuple[str, str, str]:
        return (self.record.source.value, self.record.source_instance or "",
                self.record.signal)

    @model_validator(mode="after")
    def evidence_is_coherent(self) -> Self:
        if self.admission.observation_id != self.record.observation_id:
            raise ValueError("admission assessment belongs to a different observation")
        if self.identity.observation_id != self.record.observation_id:
            raise ValueError("identity resolution belongs to a different observation")
        if self.comparability == EvidenceComparability.COMPARABLE:
            if self.comparability_reason is not None:
                raise ValueError("comparable evidence cannot carry a non-comparability reason")
        elif self.comparability_reason is None:
            raise ValueError("non-comparable evidence requires an explicit reason")
        return self


class MethodExecutionConfig(StateContract):
    """Explicit bounded-work configuration; there is no hidden operational default."""

    maximum_evidence: int = Field(gt=0)


class MethodRequest(StateContract):
    """Caller-declared method selection and descriptive scope.

    ``segment_id`` declares the arithmetic scope of segment-scoped methods; it is
    optional because a single unambiguous segment may be derived from the
    supplied evidence. A segment declaration for a method that performs no
    segment-scoped arithmetic is an explicit failure rather than a silent no-op.
    """

    configuration: MethodConfiguration
    scope: MethodScope
    ordering_basis: TimeBasis
    segment_id: str | None = Field(default=None, min_length=1)


class MethodExclusion(StateContract):
    """Evidence retained outside method support with an explicit reason code."""

    observation_id: UUID
    reason: Name
    detail: str


class MethodResult(StateContract):
    """One defensible candidate value with its exact support set.

    This is not an ``EstimatedStateField``: it carries no validity, confidence,
    uncertainty, freshness or completeness decision. Every supplied evidence item
    is accounted for exactly once, as a participant or as a reasoned exclusion.
    """

    method_name: Name
    method_version: Name
    field_contract_id: Name
    field_contract_version: Name
    configuration_sha256: Sha256
    value: float
    unit: str | None
    participants: tuple[UUID, ...]
    excluded: tuple[MethodExclusion, ...]
    metadata: FrozenMapping[str, FrozenValue]
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def accounting_is_consistent(self) -> Self:
        participants = [str(identifier) for identifier in self.participants]
        if len(set(participants)) != len(participants):
            raise ValueError("duplicate method participant")
        excluded = [str(entry.observation_id) for entry in self.excluded]
        if len(set(excluded)) != len(excluded):
            raise ValueError("duplicate method exclusion")
        if set(participants) & set(excluded):
            raise ValueError("evidence cannot be both participant and exclusion")
        return self


def _ordering_time(item: MethodEvidence, basis: TimeBasis) -> datetime | None:
    """Declared ordering time only; receipt time is never substituted for source time."""
    if basis == TimeBasis.SOURCE_OBSERVATION_TIME:
        return item.record.observation_time
    return item.record.ingestion_time


def _canonical_order(items: Sequence[MethodEvidence], basis: TimeBasis) -> tuple[MethodEvidence, ...]:
    """Deterministic chronological order; mirrors the frozen S3 continuity ordering.

    Ordering is by the declared basis time, then receipt time, then observation
    identity. Supplied input order is never semantic.
    """
    def key(item: MethodEvidence) -> tuple[datetime, datetime, str]:
        ordering_time = _ordering_time(item, basis)
        if ordering_time is None:  # pragma: no cover - unorderable evidence is filtered first
            raise SourceTimeIntervalError(
                "an ordered method requires the declared ordering-basis time")
        return (ordering_time, item.record.ingestion_time, str(item.observation_id))

    return tuple(sorted(items, key=key))


def _numeric_value(item: MethodEvidence) -> float:
    """Exact finite float of one evidence value; defects are never silently dropped."""
    value = item.record.value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NonNumericEvidenceError(
            "a numeric method cannot use non-numeric evidence")
    try:
        number = float(value)
    except OverflowError as exc:
        raise NonFiniteError(
            "evidence value cannot be represented as a finite number") from exc
    if not math.isfinite(number):
        raise NonFiniteError("evidence value is not finite")
    return number


def _basis_limitations(basis: TimeBasis, *, uses_elapsed: bool) -> tuple[str, ...]:
    """Receipt-basis ordering stays visible; it never becomes source measurement time."""
    if basis != TimeBasis.GUARDIAN_RECEIPT_TIME:
        return ()
    if uses_elapsed:
        return (RECEIPT_ORDERING_LIMITATION, RECEIPT_ELAPSED_LIMITATION)
    return (RECEIPT_ORDERING_LIMITATION,)


def _exclusion(observation_id: UUID, reason: str, detail: str) -> MethodExclusion:
    return MethodExclusion(observation_id=observation_id, reason=reason, detail=detail)


def _classify(item: MethodEvidence, *, scope: MethodScope, unit_checked: bool,
              numeric_required: bool, ordering_required: bool, source_time_required: bool,
              basis: TimeBasis,
              declared_conversion: DeclaredConversion | None) -> MethodExclusion | None:
    """Decide whether one supplied item can support the method, and why not.

    S3 outcomes are consumed exactly as supplied: excluded and context-only
    admissions stay unsupporting, unresolved identity is never repaired,
    non-comparable and identity-violating evidence never participate, and a
    numeric defect in otherwise usable evidence is surfaced rather than dropped.
    """
    if item.comparability == EvidenceComparability.IDENTITY_VIOLATION:
        return _exclusion(item.observation_id, IDENTITY_VIOLATION_REASON,
                          item.comparability_reason or "identity_integrity_violation")
    if item.comparability == EvidenceComparability.NON_COMPARABLE:
        return _exclusion(item.observation_id, NON_COMPARABLE_REASON,
                          item.comparability_reason or "non_comparable")
    if item.admission.outcome == AdmissionOutcome.EXCLUDED:
        return _exclusion(item.observation_id, ADMISSION_EXCLUDED_REASON,
                          item.admission.primary_reason)
    if item.admission.outcome == AdmissionOutcome.CONTEXT_ONLY:
        return _exclusion(item.observation_id, ADMISSION_CONTEXT_REASON,
                          item.admission.primary_reason)
    if item.identity.unresolved_components:
        return _exclusion(item.observation_id, UNRESOLVED_IDENTITY_REASON,
                          "unresolved_identity_components:" +
                          ",".join(item.identity.unresolved_components))
    if item.stream_key != scope.stream_key:
        return _exclusion(item.observation_id, STREAM_SCOPE_REASON,
                          "evidence_belongs_to_a_different_source_stream")
    if unit_checked and item.record.unit != scope.unit:
        if declared_conversion is not None and item.record.unit == declared_conversion.source_unit:
            return _exclusion(item.observation_id, UNIT_MISMATCH_DECLARED_CONVERSION_REASON,
                              "declared_conversion=" + declared_conversion.conversion_id)
        return _exclusion(item.observation_id, UNIT_MISMATCH_REASON,
                          "declared_unit_and_evidence_unit_differ")
    if item.record.value is None:
        return _exclusion(item.observation_id, VALUE_MISSING_REASON,
                          "missing_evidence_is_not_zero")
    if numeric_required:
        _numeric_value(item)
    if source_time_required and item.record.observation_time is None:
        return _exclusion(item.observation_id, SOURCE_TIME_MISSING_REASON,
                          "counter_rate_requires_source_measurement_time")
    if ordering_required and _ordering_time(item, basis) is None:
        return _exclusion(item.observation_id, UNORDERABLE_REASON,
                          "declared_ordering_basis=" + basis.value)
    return None


def _segment_scope(items: Sequence[MethodEvidence], declared_segment_id: str | None,
                   method_name: MethodName) -> tuple[tuple[MethodEvidence, ...],
                                                    tuple[MethodExclusion, ...], str | None]:
    """Resolve the one admissible analytical segment of segment-scoped arithmetic.

    Cross-segment arithmetic is never performed: when the caller declares a
    segment, evidence outside it is retained as an explicit exclusion; when no
    segment is declared, more than one segment is an explicit refusal rather than
    a hidden choice of one segment.
    """
    if method_name not in _SEGMENT_SCOPED_METHODS:
        return tuple(items), (), None
    in_scope: list[MethodEvidence] = []
    exclusions: list[MethodExclusion] = []
    for item in items:
        if item.segment_id is None:
            exclusions.append(_exclusion(
                item.observation_id, UNASSIGNED_SEGMENT_REASON,
                "evidence_is_not_assigned_to_an_analytical_segment"))
        elif declared_segment_id is not None and item.segment_id != declared_segment_id:
            exclusions.append(_exclusion(
                item.observation_id, OUTSIDE_SEGMENT_REASON,
                "evidence_belongs_to_a_different_analytical_segment"))
        else:
            in_scope.append(item)
    if declared_segment_id is not None:
        return tuple(in_scope), tuple(exclusions), declared_segment_id
    segments = sorted({item.segment_id for item in in_scope if item.segment_id is not None})
    if not segments:
        raise CrossSegmentArithmeticError(
            "within-segment arithmetic requires evidence assigned to one analytical segment")
    if len(segments) > 1:
        raise CrossSegmentArithmeticError(
            "within-segment arithmetic cannot span an analytical segment boundary")
    return tuple(in_scope), tuple(exclusions), segments[0]


def _require_single_identity_scope(items: Sequence[MethodEvidence]) -> None:
    """No hidden merge of unrelated resolved identities; cross-scope work refuses."""
    if len({item.identity.scope_key for item in items}) > 1:
        raise MethodPreconditionError(
            "eligible evidence spans more than one resolved identity scope")


@dataclass(frozen=True, slots=True)
class _Context:
    """Immutable internal inputs of one method execution."""

    method: MethodName
    version: MethodVersion
    configuration: MethodConfiguration
    parameters: _MethodParameters
    request: MethodRequest
    evidence_ids: tuple[str, ...]
    support: tuple[MethodEvidence, ...]
    ordered: tuple[MethodEvidence, ...]
    exclusions: tuple[MethodExclusion, ...]
    root_limitations: tuple[str, ...]
    segment_id: str | None


def _result_unit(context: _Context) -> str | None:
    """Missing fraction is a dimensionless ratio; every other method reports its unit."""
    if context.method == MethodName.MISSING_FRACTION:
        return None
    return context.request.scope.unit


def _assemble(context: _Context, *, value: float, participants: Sequence[MethodEvidence],
              extra_exclusions: Sequence[MethodExclusion] = (),
              limitations: Sequence[str] = (),
              metadata: Mapping[str, object] | None = None) -> MethodResult:
    """Build the immutable candidate result and enforce complete evidence accounting."""
    if not math.isfinite(value):
        raise NonFiniteError("the method produced a non-finite result")
    participant_ids = tuple(sorted({item.observation_id for item in participants}, key=str))
    excluded = [*context.exclusions, *extra_exclusions]
    excluded.sort(key=lambda entry: (str(entry.observation_id), entry.reason))
    accounted = {str(identifier) for identifier in participant_ids}
    accounted |= {str(entry.observation_id) for entry in excluded}
    if accounted != set(context.evidence_ids):
        raise MethodIntegrityError("method evidence accounting is incomplete")
    return MethodResult(
        method_name=context.method.value,
        method_version=context.version.value,
        field_contract_id=context.configuration.field_contract_id,
        field_contract_version=context.configuration.field_contract_version,
        configuration_sha256=context.configuration.configuration_sha256,
        value=value,
        unit=_result_unit(context),
        participants=participant_ids,
        excluded=tuple(excluded),
        metadata=cast("Mapping[str, FrozenValue]", dict(metadata or {})),
        limitations=tuple(dict.fromkeys((*context.root_limitations, *limitations))),
    )



def _latest(context: _Context) -> MethodResult:
    """Most recent eligible observation in the declared stream; no value-based choice."""
    orderable = context.ordered
    if not orderable:
        raise MethodPreconditionError(
            "latest eligible value requires at least one orderable eligible observation")
    basis = context.request.ordering_basis
    selected = orderable[-1]
    selected_time = _ordering_time(selected, basis)
    tied = tuple(item for item in orderable[:-1]
                 if _ordering_time(item, basis) == selected_time)
    earlier = tuple(item for item in orderable[:-1]
                    if _ordering_time(item, basis) != selected_time)
    extra = [_exclusion(item.observation_id, TIED_LATEST_REASON,
                        "same_declared_ordering_time_as_the_selected_observation")
             for item in tied]
    extra.extend(_exclusion(item.observation_id, NOT_LATEST_REASON,
                            "a_later_eligible_observation_exists_in_the_declared_scope")
                 for item in earlier)
    limitations = [CURRENTNESS_LIMITATION, *_basis_limitations(basis, uses_elapsed=False)]
    if tied:
        limitations.append(SELECTION_TIE_LIMITATION)
    metadata = {
        "ordering_basis": basis.value,
        "orderable_sample_count": len(orderable),
        "tie_count": len(tied),
        "selected_observation_id": str(selected.observation_id),
        "tied_observation_ids": tuple(sorted(str(item.observation_id) for item in tied)),
    }
    return _assemble(context, value=_numeric_value(selected), participants=(selected,),
                     extra_exclusions=tuple(extra), limitations=limitations, metadata=metadata)


def _mean(context: _Context) -> MethodResult:
    """Arithmetic sample mean: not time weighted, no smoothing or resampling."""
    values = [_numeric_value(item) for item in context.support]
    if not values:
        raise MethodPreconditionError(
            "arithmetic mean requires at least one eligible numeric observation")
    try:
        total = math.fsum(values)
    except OverflowError as exc:
        raise NonFiniteError(
            "arithmetic mean exceeded the finite numeric range") from exc
    return _assemble(context, value=total / len(values), participants=context.support,
                     metadata={"sample_count": len(values)})


def _median(context: _Context) -> MethodResult:
    """Ordered median: middle value, or the arithmetic mean of the two middle values."""
    values = sorted(_numeric_value(item) for item in context.support)
    if not values:
        raise MethodPreconditionError(
            "median requires at least one eligible numeric observation")
    count = len(values)
    middle = count // 2
    even = count % 2 == 0
    value = (values[middle - 1] + values[middle]) / 2 if even else values[middle]
    return _assemble(context, value=value, participants=context.support,
                     metadata={"sample_count": count, "even_sample_pair": even})


def _extremum(context: _Context, *, minimum: bool) -> MethodResult:
    """Deterministic extremum over eligible values; no provider preference."""
    if not context.support:
        raise MethodPreconditionError(
            f"{context.method.value} requires at least one eligible numeric observation")
    numbers = tuple((_numeric_value(item), item) for item in context.support)
    extremes = [number for number, _ in numbers]
    extreme = min(extremes) if minimum else max(extremes)
    realizers = tuple(sorted(str(item.observation_id)
                             for number, item in numbers if number == extreme))
    metadata = {
        "sample_count": len(numbers),
        "extremum_direction": "MIN" if minimum else "MAX",
        "extremum_observation_ids": realizers,
    }
    return _assemble(context, value=extreme, participants=context.support, metadata=metadata)


def _minimum(context: _Context) -> MethodResult:
    """Smallest eligible value; explicit MIN semantics over the same machinery as MAX."""
    return _extremum(context, minimum=True)


def _endpoint_parts(context: _Context) -> tuple[MethodEvidence, MethodEvidence]:
    """First and last ordered eligible observation of one declared segment.

    A negative change is preserved exactly as observed: it is never clamped and
    counter rollover is never assumed.
    """
    items = context.ordered
    if len(items) < 2:
        raise MethodPreconditionError(
            f"{context.method.value} requires at least two ordered eligible "
            "observations in one analytical segment")
    return items[0], items[-1]


def _endpoint_exclusions(context: _Context) -> tuple[MethodExclusion, ...]:
    return tuple(
        _exclusion(item.observation_id, NOT_AN_ENDPOINT_REASON,
                   "endpoint_arithmetic_uses_the_first_and_last_ordered_observation")
        for item in context.ordered[1:-1])


def _delta(context: _Context) -> MethodResult:
    """Last eligible value minus first eligible value inside one analytical segment."""
    first, last = _endpoint_parts(context)
    basis = context.request.ordering_basis
    metadata = {
        "segment_id": context.segment_id or "",
        "ordering_basis": basis.value,
        "sample_count": len(context.ordered),
        "first_observation_id": str(first.observation_id),
        "last_observation_id": str(last.observation_id),
    }
    return _assemble(
        context, value=_numeric_value(last) - _numeric_value(first),
        participants=(first, last), extra_exclusions=_endpoint_exclusions(context),
        limitations=_basis_limitations(basis, uses_elapsed=False), metadata=metadata)


def _rate(context: _Context) -> MethodResult:
    """Observed counter change per strictly positive unit of source-time interval."""
    first, last = _endpoint_parts(context)
    basis = context.request.ordering_basis
    first_time = first.record.observation_time
    last_time = last.record.observation_time
    if first_time is None or last_time is None:  # pragma: no cover - filtered as unusable
        raise SourceTimeIntervalError(
            "receipt timing cannot substitute for source measurement time in a counter rate")
    elapsed = (last_time - first_time).total_seconds()
    if elapsed <= 0:
        raise SourceTimeIntervalError(
            "a counter rate requires a strictly positive source-time interval")
    metadata = {
        "segment_id": context.segment_id or "",
        "ordering_basis": basis.value,
        "sample_count": len(context.ordered),
        "elapsed_source_seconds": elapsed,
        "first_observation_id": str(first.observation_id),
        "last_observation_id": str(last.observation_id),
    }
    return _assemble(
        context, value=(_numeric_value(last) - _numeric_value(first)) / elapsed,
        participants=(first, last), extra_exclusions=_endpoint_exclusions(context),
        limitations=(COUNTER_SCOPE_LIMITATION, *_basis_limitations(basis, uses_elapsed=True)),
        metadata=metadata)


def _slope(context: _Context) -> MethodResult:
    """Descriptive historical endpoint slope: endpoint change over elapsed time."""
    first, last = _endpoint_parts(context)
    basis = context.request.ordering_basis
    first_time = _ordering_time(first, basis)
    last_time = _ordering_time(last, basis)
    if first_time is None or last_time is None:  # pragma: no cover - filtered as unusable
        raise SourceTimeIntervalError(
            "historical endpoint slope requires a known ordering time")
    elapsed = (last_time - first_time).total_seconds()
    if elapsed <= 0:
        raise SourceTimeIntervalError(
            "historical endpoint slope requires a strictly positive elapsed interval")
    metadata = {
        "segment_id": context.segment_id or "",
        "ordering_basis": basis.value,
        "sample_count": len(context.ordered),
        "elapsed_seconds": elapsed,
        "first_observation_id": str(first.observation_id),
        "last_observation_id": str(last.observation_id),
    }
    return _assemble(
        context, value=(_numeric_value(last) - _numeric_value(first)) / elapsed,
        participants=(first, last), extra_exclusions=_endpoint_exclusions(context),
        limitations=(SLOPE_DESCRIPTIVE_LIMITATION,
                     *_basis_limitations(basis, uses_elapsed=True)),
        metadata=metadata)


def _missing_fraction(context: _Context) -> MethodResult:
    """Missing opportunities over an explicit expected-opportunity denominator."""
    expected = context.parameters.expected_opportunities
    if expected is None:  # pragma: no cover - configuration requires an explicit value
        raise MethodConfigurationError(
            "missing fraction requires an explicit expected-opportunity denominator")
    observed = len(context.support)
    if observed > expected:
        raise MethodPreconditionError(
            "observed eligible opportunities exceed the declared expected opportunities")
    metadata = {
        "expected_opportunities": expected,
        "observed_opportunities": observed,
        "missing_opportunities": expected - observed,
    }
    return _assemble(context, value=(expected - observed) / expected,
                     participants=context.support,
                     limitations=(MISSING_FRACTION_LIMITATION,), metadata=metadata)


def _maximum(context: _Context) -> MethodResult:
    """Largest eligible value; explicit MAX semantics over the same machinery as MIN."""
    return _extremum(context, minimum=False)


# Explicit dispatch surface: exactly the authorized generic methods, immutable and
# never mutated at runtime. There is no default entry and no fallback handler.
_DISPATCH: Mapping[MethodName, Callable[[_Context], MethodResult]] = MappingProxyType({
    MethodName.LATEST_ELIGIBLE_VALUE: _latest,
    MethodName.ARITHMETIC_MEAN: _mean,
    MethodName.MEDIAN: _median,
    MethodName.MIN: _minimum,
    MethodName.MAX: _maximum,
    MethodName.WITHIN_SEGMENT_DELTA: _delta,
    MethodName.SOURCE_TIME_COUNTER_RATE: _rate,
    MethodName.HISTORICAL_ENDPOINT_SLOPE: _slope,
    MethodName.MISSING_FRACTION: _missing_fraction,
})


def compute_candidate(evidence: Sequence[MethodEvidence], request: MethodRequest,
                      config: MethodExecutionConfig) -> MethodResult:
    """Execute exactly the caller-selected method over bounded supplied evidence.

    Order of operations: canonicalize the bounded input, dispatch the exact
    declared method/version, re-validate the declared parameter surface, classify
    each item against the frozen S3 outcomes (never re-admitting, repairing or
    merging anything), resolve the one admissible analytical segment when the
    method requires it, then compute the descriptive value. Any failure is
    surfaced as an explicit typed error; no defect is ever converted into a
    numeric value and no alternative estimator is ever chosen.
    """
    try:
        config = MethodExecutionConfig.model_validate(config.model_dump(warnings=False))
        request = MethodRequest.model_validate(request.model_dump(warnings=False))
    except (AttributeError, TypeError, ValueError) as exc:
        raise MethodConfigurationError("invalid method-execution request") from exc
    try:
        supplied = tuple(evidence)
    except TypeError as exc:
        raise MethodIntegrityError("method evidence is not a bounded supplied collection") from exc
    if len(supplied) > config.maximum_evidence:
        raise MethodLimitError("method execution exceeds the evidence budget")

    canonical: list[MethodEvidence] = []
    for item in supplied:
        try:
            canonical.append(MethodEvidence.model_validate(item.model_dump(warnings=False)))
        except (AttributeError, TypeError, ValueError) as exc:
            raise MethodIntegrityError("invalid method evidence") from exc
    identifiers = [str(item.observation_id) for item in canonical]
    if len(set(identifiers)) != len(identifiers):
        raise MethodIntegrityError("duplicate evidence identity in method execution")

    method, version = request.configuration.resolved()
    parameters = _resolve_parameters(method, request.configuration)
    if request.segment_id is not None and method not in _SEGMENT_SCOPED_METHODS:
        raise MethodConfigurationError(
            "a declared segment scope is not part of this method's semantics")
    conversion = parameters.declared_conversion
    if conversion is not None and conversion.target_unit != (request.scope.unit or ""):
        raise MethodConfigurationError(
            "the declared conversion target unit does not match the declared scope unit")
    for item in canonical:
        if (item.admission.field_contract_id != request.configuration.field_contract_id
                or item.admission.field_contract_version
                != request.configuration.field_contract_version):
            raise MethodIntegrityError(
                "admission assessment was produced under a different field contract")

    basis = request.ordering_basis
    support: list[MethodEvidence] = []
    exclusions: list[MethodExclusion] = []
    for item in canonical:
        exclusion = _classify(
            item, scope=request.scope,
            unit_checked=method in _UNIT_CHECKED_METHODS,
            numeric_required=method in _NUMERIC_METHODS,
            ordering_required=method in _ORDERED_METHODS,
            source_time_required=method == MethodName.SOURCE_TIME_COUNTER_RATE,
            basis=basis, declared_conversion=conversion)
        if exclusion is None:
            support.append(item)
        else:
            exclusions.append(exclusion)

    root_limitations: list[str] = []
    if any(entry.reason == UNIT_MISMATCH_DECLARED_CONVERSION_REASON for entry in exclusions):
        root_limitations.append(CONVERSION_ROOT_LIMITATION)
    if any(entry.reason == IDENTITY_VIOLATION_REASON for entry in exclusions):
        root_limitations.append(IDENTITY_VIOLATION_LIMITATION)

    in_scope, segment_exclusions, segment_id = _segment_scope(
        tuple(support), request.segment_id, method)
    exclusions.extend(segment_exclusions)
    _require_single_identity_scope(in_scope)
    ordered = _canonical_order(in_scope, basis) if method in _ORDERED_METHODS else ()
    context = _Context(
        method=method, version=version, configuration=request.configuration,
        parameters=parameters, request=request, evidence_ids=tuple(identifiers),
        support=in_scope, ordered=ordered, exclusions=tuple(exclusions),
        root_limitations=tuple(dict.fromkeys(root_limitations)), segment_id=segment_id,
    )
    return _DISPATCH[method](context)

