"""Versioned M3.2 state shapes. Producers and persistence belong to later slices."""

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PlainSerializer,
    PlainValidator,
    SerializerFunctionWrapHandler,
    StringConstraints,
    TypeAdapter,
    WrapSerializer,
    field_validator,
    model_validator,
)

from mining_guardian.observability.models import Freshness, Quality, utc

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$")]
Name = Annotated[str, StringConstraints(min_length=1)]

type FrozenJson = bool | int | float | str | tuple[FrozenJson, ...] | Mapping[str, FrozenJson] | None
_JSON: TypeAdapter[JsonValue] = TypeAdapter(JsonValue, config=ConfigDict(allow_inf_nan=False))


def _freeze_json(value: JsonValue) -> FrozenJson:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _json_copy(value: FrozenJson) -> JsonValue:
    if isinstance(value, Mapping):
        return {key: _json_copy(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_copy(item) for item in value]
    return value


def _validated_frozen_json(value: object) -> FrozenJson:
    # Accept our own immutable representation on reconstruction as well as JSON.
    if isinstance(value, (MappingProxyType, tuple)):
        value = _json_copy(value)
    return _freeze_json(_JSON.validate_python(value))


FrozenValue = Annotated[
    FrozenJson,
    PlainValidator(_validated_frozen_json),
    PlainSerializer(_json_copy, return_type=JsonValue),
]


def _immutable_mapping[K, V](value: Mapping[K, V]) -> Mapping[K, V]:
    return MappingProxyType(dict(value))


def _serialize_mapping(value: Mapping[object, object], handler: SerializerFunctionWrapHandler) -> object:
    return handler(dict(value))


type FrozenMapping[K, V] = Annotated[
    Mapping[K, V], AfterValidator(_immutable_mapping), WrapSerializer(_serialize_mapping)
]


class StateContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class StateValidity(StrEnum):
    VALID = "VALID"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"


class SnapshotCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class SupportStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    LIMITED = "LIMITED"
    UNASSESSED = "UNASSESSED"


class SupportCheckKind(StrEnum):
    MINIMUM = "MINIMUM"
    STRENGTHENING = "STRENGTHENING"


class CheckResult(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class UncertaintyDimension(StrEnum):
    MEASUREMENT = "measurement"
    TEMPORAL = "temporal"
    SOURCE_DISAGREEMENT = "source_disagreement"
    EVIDENCE_INCOMPLETENESS = "evidence_incompleteness"
    IDENTITY = "identity"
    METHOD = "method"


class UncertaintyStatus(StrEnum):
    QUANTIFIED = "QUANTIFIED"
    KNOWN_UNQUANTIFIED = "KNOWN_UNQUANTIFIED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EvidenceDisposition(StrEnum):
    SUPPORTING = "SUPPORTING"
    OPTIONAL_SUPPORT = "OPTIONAL_SUPPORT"
    CONFLICTING = "CONFLICTING"
    EXCLUDED = "EXCLUDED"
    CONTEXT_ONLY = "CONTEXT_ONLY"


class ConflictKind(StrEnum):
    VALUE_DISAGREEMENT = "VALUE_DISAGREEMENT"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    TEMPORAL_MISALIGNMENT = "TEMPORAL_MISALIGNMENT"
    UNIT_OR_SEMANTIC_MISMATCH = "UNIT_OR_SEMANTIC_MISMATCH"


class ConflictResolutionStatus(StrEnum):
    UNRESOLVED = "UNRESOLVED"
    RESOLVED = "RESOLVED"


class TimeBasis(StrEnum):
    SOURCE_OBSERVATION_TIME = "source_observation_time"
    GUARDIAN_RECEIPT_TIME = "guardian_receipt_time"


class StateEvidenceReference(StateContract):
    observation_id: UUID
    observation_schema_version: Name
    payload_sha256: Sha256 | None = None
    immutable_payload_ref: Name | None = None
    source: Name
    source_instance: str | None
    signal: Name
    unit: str | None
    event_time: datetime | None
    observation_time: datetime | None
    ingestion_time: datetime
    processing_time: datetime | None
    guardian_session_id: str | None
    correlation_id: UUID | None
    input_quality: Quality
    input_quality_conditions: tuple[Quality, ...]
    recorded_freshness: Freshness
    temporal_assessment: Name
    disposition: EvidenceDisposition
    reason: Name

    @field_validator("event_time", "observation_time", "ingestion_time", "processing_time")
    @classmethod
    def aware_utc(cls, value: datetime | None) -> datetime | None:
        return utc(value) if value is not None else None

    @model_validator(mode="after")
    def has_immutable_source(self) -> Self:
        if self.payload_sha256 is None and self.immutable_payload_ref is None:
            raise ValueError("evidence reference needs a digest or immutable payload reference")
        return self


class SupportCheck(StateContract):
    check_id: Name
    kind: SupportCheckKind
    result: CheckResult
    evidence_ids: tuple[UUID, ...] = ()


class StateConfidence(StateContract):
    interpretation: Literal["CURRENT_ESTIMATE_SUPPORT"]
    rubric_id: Name
    rubric_version: Name
    support_status: SupportStatus
    support_checks: tuple[SupportCheck, ...]
    reason_codes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def checks_agree_with_status(self) -> Self:
        if len({check.check_id for check in self.support_checks}) != len(self.support_checks):
            raise ValueError("duplicate support check identity")
        minimum = [c for c in self.support_checks if c.kind == SupportCheckKind.MINIMUM]
        strengthening = [c for c in self.support_checks if c.kind == SupportCheckKind.STRENGTHENING]
        if (self.support_status == SupportStatus.SUPPORTED
                and (not any(c.result == CheckResult.PASS for c in self.support_checks) or any(
                    c.result not in (CheckResult.PASS, CheckResult.NOT_APPLICABLE)
                    for c in self.support_checks))):
            raise ValueError("SUPPORTED requires all applicable checks to pass")
        if self.support_status == SupportStatus.LIMITED:
            if not minimum or any(c.result != CheckResult.PASS for c in minimum):
                raise ValueError("LIMITED requires passing minimum checks")
            if not any(c.result in (CheckResult.FAIL, CheckResult.UNKNOWN) for c in strengthening):
                raise ValueError("LIMITED requires a failed or unknown strengthening check")
        return self


class UncertaintyAssessment(StateContract):
    status: UncertaintyStatus
    reason: Name
    evidence_ids: tuple[UUID, ...] = ()
    quantification: float | tuple[float, float] | None = None
    unit: str | None = None
    method_name: str | None = None
    method_version: str | None = None
    assumptions: tuple[str, ...] = ()
    coverage_interpretation: str | None = None
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def justified_quantification(self) -> Self:
        if self.status == UncertaintyStatus.QUANTIFIED:
            if (self.quantification is None or not self.unit or not self.method_name
                    or not self.method_version or not self.assumptions):
                raise ValueError("quantification requires value, unit, method and assumptions")
            if isinstance(self.quantification, tuple) and self.quantification[0] > self.quantification[1]:
                raise ValueError("uncertainty interval is reversed")
        elif self.quantification is not None:
            raise ValueError("unquantified uncertainty cannot carry a numeric value")
        if self.status == UncertaintyStatus.KNOWN_UNQUANTIFIED and not self.limitations:
            raise ValueError("known unquantified uncertainty needs an explicit limitation")
        return self


class StateUncertainty(StateContract):
    dimensions: FrozenMapping[UncertaintyDimension, UncertaintyAssessment]

    @model_validator(mode="after")
    def all_dimensions_explicit(self) -> Self:
        if set(self.dimensions) != set(UncertaintyDimension):
            raise ValueError("every accepted uncertainty dimension must be explicit")
        return self


class EvidenceCompleteness(StateContract):
    required: tuple[Name, ...]
    satisfied: tuple[Name, ...]
    unavailable: tuple[Name, ...]
    conflicting: tuple[Name, ...]
    optional_support: tuple[Name, ...]

    @model_validator(mode="after")
    def coherent_requirements(self) -> Self:
        groups = (self.required, self.satisfied, self.unavailable, self.conflicting, self.optional_support)
        if any(len(set(group)) != len(group) for group in groups):
            raise ValueError("duplicate evidence requirement")
        required = set(self.required)
        dispositions = (set(self.satisfied), set(self.unavailable), set(self.conflicting))
        if any(not group <= required for group in dispositions):
            raise ValueError("unknown required evidence identifier")
        if any(dispositions[i] & dispositions[j] for i, j in ((0, 1), (0, 2), (1, 2))):
            raise ValueError("one requirement cannot have conflicting dispositions")
        if set(self.optional_support) & required:
            raise ValueError("optional evidence must remain distinct from required evidence")
        return self


class SignalRequirement(StateContract):
    source: Name
    signal: Name
    source_semantics: Name
    unit: str | None


class FieldEvidenceContract(StateContract):
    contract_id: Name
    contract_version: Name
    field_key: Name
    estimand: Name
    subject_scope: Name
    required_signals: tuple[SignalRequirement, ...] = Field(min_length=1)
    optional_signals: tuple[SignalRequirement, ...]
    identity_requirements: tuple[Name, ...]
    allowed_units: tuple[Name, ...]
    allowed_conversions: tuple[Name, ...]
    admissible_quality: tuple[Quality, ...]
    temporal_basis: TimeBasis
    window_seconds: float = Field(gt=0)
    minimum_samples: int = Field(ge=1)
    minimum_span_seconds: float = Field(ge=0)
    terminal_recency_seconds: float | None = Field(default=None, ge=0)
    maximum_alignment_seconds: float | None = Field(default=None, ge=0)
    minimum_coverage_fraction: float | None = Field(ge=0, le=1)
    maximum_gap_seconds: float | None = Field(gt=0)
    continuity_rule: Name
    conflict_rule: Name
    permitted_degradation_rules: tuple[Name, ...]
    confidence_rubric_id: Name
    confidence_rubric_version: Name
    output_type: Name
    output_unit: str | None
    maximum_records: int = Field(gt=0)
    maximum_decoded_bytes: int = Field(gt=0)
    maximum_subjects: int = Field(gt=0)
    predecessor_lookback_seconds: float = Field(ge=0)

    @model_validator(mode="after")
    def distinct_signals(self) -> Self:
        if self.minimum_span_seconds > self.window_seconds:
            raise ValueError("minimum span exceeds evidence window")
        if self.terminal_recency_seconds is not None and self.terminal_recency_seconds > self.window_seconds:
            raise ValueError("terminal recency exceeds evidence window")
        required = {(r.source, r.signal) for r in self.required_signals}
        optional = {(r.source, r.signal) for r in self.optional_signals}
        if len(required) != len(self.required_signals) or len(optional) != len(self.optional_signals):
            raise ValueError("duplicate signal requirement")
        if required & optional:
            raise ValueError("one signal cannot be both required and optional")
        return self


class StateConflict(StateContract):
    conflict_id: UUID
    affected_field_key: Name
    kind: ConflictKind
    participant_evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    comparison_contract_id: Name
    comparison_contract_version: Name
    comparison_basis: Name
    resolution_status: ConflictResolutionStatus
    reason: Name
    resolution_rule_id: str | None = None
    resolution_rule_version: str | None = None
    selected_evidence_ids: tuple[UUID, ...] = ()
    rejected_evidence_ids: tuple[UUID, ...] = ()
    quantified_disagreement: float | None = None
    disagreement_unit: str | None = None

    @model_validator(mode="after")
    def participants_preserved(self) -> Self:
        participants = set(self.participant_evidence_ids)
        if len(participants) != len(self.participant_evidence_ids):
            raise ValueError("duplicate conflict participant")
        if self.kind == ConflictKind.VALUE_DISAGREEMENT and len(participants) < 2:
            raise ValueError("value disagreement requires at least two participants")
        if not set(self.selected_evidence_ids) <= participants or not set(self.rejected_evidence_ids) <= participants:
            raise ValueError("conflict selection references a nonparticipant")
        if bool(self.resolution_rule_id) != bool(self.resolution_rule_version):
            raise ValueError("resolution rule identity and version must be paired")
        if self.selected_evidence_ids and self.resolution_rule_id is None:
            raise ValueError("selected conflict evidence requires a versioned resolution rule")
        if set(self.selected_evidence_ids) & set(self.rejected_evidence_ids):
            raise ValueError("conflict evidence cannot be both selected and rejected")
        if self.quantified_disagreement is not None and not self.disagreement_unit:
            raise ValueError("quantified disagreement needs a unit")
        if self.resolution_status == ConflictResolutionStatus.RESOLVED:
            if not (self.resolution_rule_id and self.resolution_rule_id.strip()
                    and self.resolution_rule_version and self.resolution_rule_version.strip()
                    and self.reason.strip()):
                raise ValueError("RESOLVED requires a substantive versioned resolution rule and reason")
            if (self.kind == ConflictKind.VALUE_DISAGREEMENT
                    and not (self.selected_evidence_ids or self.rejected_evidence_ids)):
                raise ValueError("RESOLVED value disagreement requires explicit participant outcomes")
        elif self.selected_evidence_ids or self.rejected_evidence_ids:
            raise ValueError("UNRESOLVED cannot select or reject participants")
        return self


class LastKnownContext(StateContract):
    value: FrozenValue
    observation_id: UUID
    source_time: datetime | None
    receipt_time: datetime
    age_seconds: float | None = Field(ge=0)
    age_assessment: Name

    @field_validator("source_time", "receipt_time")
    @classmethod
    def aware_utc(cls, value: datetime | None) -> datetime | None:
        return utc(value) if value is not None else None

    @model_validator(mode="after")
    def known_value(self) -> Self:
        if self.value is None:
            raise ValueError("last-known context needs a value")
        return self


class FieldRequest(StateContract):
    field_key: Name
    subject_scope: Name


class EstimatedStateField(StateContract):
    field_key: Name
    subject_scope: Name
    definition_version: Name
    value: FrozenValue
    unit: str | None
    state_reference_time: datetime
    validity: StateValidity
    confidence: StateConfidence
    uncertainty: StateUncertainty
    evidence_completeness: EvidenceCompleteness
    freshness_assessment: Name
    method_name: Name
    method_version: Name
    field_contract_id: Name
    field_contract_version: Name
    configuration: FrozenMapping[str, FrozenValue]
    configuration_sha256: Sha256
    evidence_refs: tuple[StateEvidenceReference, ...]
    conflicts: tuple[StateConflict, ...] = ()
    limitations: tuple[str, ...] = ()
    failure_reason: str | None = None
    degradation_rule_id: str | None = None
    degradation_rule_version: str | None = None
    continuity_segment_ref: str | None = None
    last_known: LastKnownContext | None = None

    @field_validator("state_reference_time")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        return utc(value)

    @model_validator(mode="after")
    def value_matches_assessment(self) -> Self:
        has_value = self.value is not None
        if has_value != (self.validity in (StateValidity.VALID, StateValidity.DEGRADED)):
            raise ValueError("field value and validity disagree")
        if self.validity == StateValidity.INVALID and not (self.failure_reason and self.failure_reason.strip()):
            raise ValueError("INVALID requires positive failure evidence")
        if self.validity == StateValidity.DEGRADED and not (self.degradation_rule_id and self.degradation_rule_version):
            raise ValueError("DEGRADED requires an explicit versioned rule")
        if self.validity == StateValidity.VALID and (
            set(self.evidence_completeness.required) != set(self.evidence_completeness.satisfied)
            or self.evidence_completeness.unavailable or self.evidence_completeness.conflicting
        ):
            raise ValueError("VALID requires all declared required evidence")
        if not has_value and self.confidence.support_status != SupportStatus.UNASSESSED:
            raise ValueError("unavailable current value cannot claim assessed support")
        ids = [r.observation_id for r in self.evidence_refs]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate field evidence reference")
        if has_value and not any(r.disposition == EvidenceDisposition.SUPPORTING for r in self.evidence_refs):
            raise ValueError("estimated value requires supporting observation identity")
        if any(c.affected_field_key != self.field_key for c in self.conflicts):
            raise ValueError("conflict belongs to a different field")
        if any(not set(c.participant_evidence_ids) <= set(ids) for c in self.conflicts):
            raise ValueError("conflict participants must be retained in field evidence")
        if has_value and any(c.kind == ConflictKind.VALUE_DISAGREEMENT
                             and c.resolution_status == ConflictResolutionStatus.UNRESOLVED
                             for c in self.conflicts):
            raise ValueError("unresolved comparable conflict requires UNKNOWN or INVALID current field")
        return self


class StateSnapshot(StateContract):
    state_reference_time: datetime
    requested_fields: tuple[FieldRequest, ...] = Field(min_length=1)
    fields: tuple[EstimatedStateField, ...]
    completeness: SnapshotCompleteness
    usable_fields: tuple[FieldRequest, ...]
    unavailable_fields: tuple[FieldRequest, ...]
    invalid_fields: tuple[FieldRequest, ...]
    input_manifest_id: Sha256
    schema_version: Literal["m3.2.state-snapshot.v1"] = "m3.2.state-snapshot.v1"

    @field_validator("state_reference_time")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        return utc(value)

    @model_validator(mode="after")
    def requested_scope_and_summary_agree(self) -> Self:
        requested = [(r.subject_scope, r.field_key) for r in self.requested_fields]
        actual = [(f.subject_scope, f.field_key) for f in self.fields]
        if len(set(requested)) != len(requested) or len(set(actual)) != len(actual):
            raise ValueError("duplicate field identity")
        if requested != actual:
            raise ValueError("requested field inventory differs from snapshot fields")
        if any(f.state_reference_time != self.state_reference_time for f in self.fields):
            raise ValueError("snapshot fields have inconsistent reference times")
        by_validity = {status: tuple(r for r, f in zip(self.requested_fields, self.fields, strict=True)
                                     if f.validity == status) for status in StateValidity}
        usable = tuple(r for r, f in zip(self.requested_fields, self.fields, strict=True)
                       if f.validity in (StateValidity.VALID, StateValidity.DEGRADED))
        if (self.usable_fields != usable
                or self.unavailable_fields != by_validity[StateValidity.UNKNOWN]
                or self.invalid_fields != by_validity[StateValidity.INVALID]):
            raise ValueError("snapshot field lists disagree with field assessments")
        expected = (SnapshotCompleteness.COMPLETE if all(f.validity == StateValidity.VALID for f in self.fields)
                    else SnapshotCompleteness.PARTIAL if usable else SnapshotCompleteness.UNAVAILABLE)
        if self.completeness != expected:
            raise ValueError("snapshot completeness disagrees with fields")
        return self


class ProductionMetadata(StateContract):
    artifact_id: UUID
    estimated_at: datetime
    supersedes_artifact_id: UUID | None = None

    @field_validator("estimated_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        return utc(value)

    @model_validator(mode="after")
    def distinct_supersession(self) -> Self:
        if self.supersedes_artifact_id == self.artifact_id:
            raise ValueError("artifact cannot supersede itself")
        return self


class EstimatedState(StateContract):
    state_type: Name
    snapshot: StateSnapshot
    semantic_content_id: Sha256
    production: ProductionMetadata
    schema_version: Literal["m3.2.estimated-state.v1"] = "m3.2.estimated-state.v1"

    @property
    def state_id(self) -> UUID:
        return self.production.artifact_id

    @property
    def effective_time(self) -> datetime:
        return self.snapshot.state_reference_time
