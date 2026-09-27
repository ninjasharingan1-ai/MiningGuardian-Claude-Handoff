"""M3.2-S3 comparable conflict detection with no hidden winner.

Conflicts preserve every participant. Comparable disagreement is recorded only
when subject, quantity, unit and effective interval are demonstrably compatible.
There is initially no general cross-source winner: no latest-wins rule, no
preferred or ranked source, no averaging, majority vote or maximum/minimum
selection, and no provider precedence. Source failure and missingness are not
disagreement, and a shared acquisition identity is never treated as physical
simultaneity.

Every supplied candidate is accounted for exactly once, as either a conflict
participant, an agreement participant, or an explicit not-compared entry, so a
candidate can never be silently dropped.
"""

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import Field, JsonValue, field_validator, model_validator

from mining_guardian.observability.models import Source, utc
from mining_guardian.state.contracts import (
    ConflictKind,
    ConflictResolutionStatus,
    Name,
    StateConflict,
    StateContract,
    TimeBasis,
)
from mining_guardian.state.subjects import (
    IdentityComponentStatus,
    IdentityResolution,
    deterministic_uuid,
)

CONFLICT_METHOD = "m3.2.conflict-detection"
CONFLICT_METHOD_VERSION = "v1"
NO_WINNER_LIMITATION = "no_general_cross_source_resolution_policy_exists_in_this_slice"
RECEIPT_ALIGNMENT_LIMITATION = "receipt_basis_alignment_is_not_physical_simultaneity"
ACQUISITION_LIMITATION = "shared_acquisition_identity_is_not_physical_simultaneity"
SOURCE_INSTANCE_LIMITATION = "source_instance_unavailable"


class ConflictDetectionError(RuntimeError):
    """Base class for explicit conflict-detection failures."""


class ConflictDetectionIntegrityError(ConflictDetectionError):
    """Supplied evidence or comparison scope is inconsistent with its contract."""


class ConflictDetectionLimitError(ConflictDetectionError):
    """A declared bounded-work ceiling was exceeded."""


class ValueKind(StrEnum):
    BOOLEAN = "BOOLEAN"
    NUMBER = "NUMBER"
    STRING = "STRING"
    ARRAY = "ARRAY"
    OBJECT = "OBJECT"
    NULL = "NULL"


class QuantityDeclaration(StateContract):
    """One declared quantity identity; different meanings are never comparable."""

    quantity_id: Name
    signals: tuple[Name, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def distinct_signals(self) -> Self:
        if len(set(self.signals)) != len(self.signals):
            raise ValueError("duplicate signal in quantity declaration")
        return self


class ComparisonContract(StateContract):
    """Versioned comparability contract; alignment tolerance is never invented."""

    contract_id: Name
    contract_version: Name
    comparison_basis: Name
    maximum_alignment_seconds: float | None = None
    quantities: tuple[QuantityDeclaration, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def coherent_quantities(self) -> Self:
        if self.maximum_alignment_seconds is not None and self.maximum_alignment_seconds < 0:
            raise ValueError("declared alignment tolerance cannot be negative")
        identifiers = [quantity.quantity_id for quantity in self.quantities]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("duplicate quantity declaration")
        signals = [signal for quantity in self.quantities for signal in quantity.signals]
        if len(set(signals)) != len(signals):
            raise ValueError("one signal cannot declare two quantities")
        return self


class ExpectedIdentity(StateContract):
    """Declared comparison scope; declared components must match resolved evidence."""

    subject_id: Name
    workload_id: Name | None = None
    algorithm_id: Name | None = None


class ComparisonRequest(StateContract):
    affected_field_key: Name
    quantity_id: Name
    expected_identity: ExpectedIdentity


class ComparableEvidence(StateContract):
    """One eligible, scoped candidate offered for comparison."""

    observation_id: UUID
    source: Source
    source_instance: str | None = None
    signal: Name
    unit: str | None = None
    value: JsonValue = None
    effective_basis: TimeBasis
    effective_time: datetime
    correlation_id: UUID | None = None
    identity: IdentityResolution

    @field_validator("effective_time")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        return utc(value)

    @model_validator(mode="after")
    def identity_belongs_to_evidence(self) -> Self:
        if self.identity.observation_id != self.observation_id:
            raise ValueError("comparison identity belongs to a different observation")
        return self


class ConflictDetectionConfig(StateContract):
    """Explicit bounded-work configuration; there is no hidden operational default."""

    maximum_candidates: int = Field(gt=0)


class ComparableAgreement(StateContract):
    """Recorded corroboration; it is not a winner and does not rank sources."""

    quantity_id: Name
    comparison_basis: Name
    participant_evidence_ids: tuple[UUID, ...] = Field(min_length=2)
    source_streams: tuple[str, ...] = Field(min_length=2)
    agreed_value: JsonValue = None
    unit: str | None = None
    effective_basis: TimeBasis
    effective_time_spread_seconds: float = Field(ge=0)

    @model_validator(mode="after")
    def distinct_participants(self) -> Self:
        if len(set(self.participant_evidence_ids)) != len(self.participant_evidence_ids):
            raise ValueError("duplicate agreement participant")
        if len(set(self.source_streams)) != len(self.source_streams):
            raise ValueError("duplicate agreement source stream")
        return self


class NotComparedEvidence(StateContract):
    """Candidate retained outside comparison with an explicit reason."""

    observation_id: UUID
    reason: Name
    detail: str


class ConflictDetectionResult(StateContract):
    """Conflicts, agreements and explicit not-compared evidence; no hidden winner."""

    conflicts: tuple[StateConflict, ...] = ()
    agreements: tuple[ComparableAgreement, ...] = ()
    not_compared: tuple[NotComparedEvidence, ...] = ()
    affected_field_key: Name
    quantity_id: Name
    contract_id: Name
    contract_version: Name
    comparison_basis: Name
    limitations: tuple[str, ...] = ()
    method_name: Name = CONFLICT_METHOD
    method_version: Name = CONFLICT_METHOD_VERSION

    @model_validator(mode="after")
    def every_candidate_accounted_once(self) -> Self:
        accounted = [identifier for conflict in self.conflicts
                     for identifier in conflict.participant_evidence_ids]
        accounted += [identifier for agreement in self.agreements
                       for identifier in agreement.participant_evidence_ids]
        accounted += [entry.observation_id for entry in self.not_compared]
        if len(set(accounted)) != len(accounted):
            raise ValueError("one candidate cannot be accounted for twice")
        if any(conflict.affected_field_key != self.affected_field_key for conflict in self.conflicts):
            raise ValueError("conflict belongs to a different affected field")
        if any(conflict.selected_evidence_ids or conflict.rejected_evidence_ids
               for conflict in self.conflicts):
            raise ValueError("this slice cannot select or reject conflict participants")
        if any(conflict.resolution_status != ConflictResolutionStatus.UNRESOLVED
               for conflict in self.conflicts):
            raise ValueError("this slice emits unresolved conflicts only")
        return self


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _value_kind(value: object) -> ValueKind:
    if isinstance(value, bool):
        return ValueKind.BOOLEAN
    if isinstance(value, (int, float)):
        return ValueKind.NUMBER
    if isinstance(value, str):
        return ValueKind.STRING
    if isinstance(value, (list, tuple)):
        return ValueKind.ARRAY
    if isinstance(value, dict):
        return ValueKind.OBJECT
    return ValueKind.NULL


def _stream(candidate: ComparableEvidence) -> str:
    return f"{candidate.source.value}:{candidate.source_instance or ''}"


def _participants(candidates: Sequence[ComparableEvidence]) -> tuple[UUID, ...]:
    return tuple(sorted((candidate.observation_id for candidate in candidates), key=str))


def _matches_request(identity: IdentityResolution, expected: ExpectedIdentity) -> bool:
    if (identity.subject.status != IdentityComponentStatus.RESOLVED
            or identity.subject.resolved_id != expected.subject_id):
        return False
    declared = ((identity.workload, expected.workload_id), (identity.algorithm, expected.algorithm_id))
    return all(component.status == IdentityComponentStatus.RESOLVED and component.resolved_id == value
               for component, value in declared if value is not None)


def _build_conflict(kind: ConflictKind, candidates: Sequence[ComparableEvidence], *,
                    request: ComparisonRequest, contract: ComparisonContract, reason: str,
                    quantified: float | None = None, unit: str | None = None) -> StateConflict:
    participants = _participants(candidates)
    expected = request.expected_identity
    conflict_id = deterministic_uuid("state-conflict", (
        request.affected_field_key, kind.value, contract.contract_id, contract.contract_version,
        contract.comparison_basis, request.quantity_id, expected.subject_id,
        expected.workload_id or "", expected.algorithm_id or "",
        *(str(identifier) for identifier in participants),
        ConflictResolutionStatus.UNRESOLVED.value, reason,
    ))
    return StateConflict(
        conflict_id=conflict_id,
        affected_field_key=request.affected_field_key,
        kind=kind,
        participant_evidence_ids=participants,
        comparison_contract_id=contract.contract_id,
        comparison_contract_version=contract.contract_version,
        comparison_basis=contract.comparison_basis,
        resolution_status=ConflictResolutionStatus.UNRESOLVED,
        reason=reason,
        quantified_disagreement=quantified,
        disagreement_unit=unit if quantified is not None else None,
    )


def _same_value(first: JsonValue, second: JsonValue) -> bool:
    return type(first) is type(second) and first == second


def _distinct_values(values: Sequence[JsonValue]) -> list[JsonValue]:
    distinct: list[JsonValue] = []
    for value in values:
        if not any(_same_value(value, existing) for existing in distinct):
            distinct.append(value)
    return distinct


def _build_agreement(candidates: Sequence[ComparableEvidence], *, request: ComparisonRequest,
                     contract: ComparisonContract, agreed_value: JsonValue, unit: str | None,
                     basis: TimeBasis, spread: float) -> ComparableAgreement:
    return ComparableAgreement(
        quantity_id=request.quantity_id,
        comparison_basis=contract.comparison_basis,
        participant_evidence_ids=_participants(candidates),
        source_streams=tuple(sorted({_stream(candidate) for candidate in candidates})),
        agreed_value=agreed_value,
        unit=unit,
        effective_basis=basis,
        effective_time_spread_seconds=spread,
    )


def detect_conflicts(candidates: Sequence[ComparableEvidence], contract: ComparisonContract,
                     request: ComparisonRequest, config: ConflictDetectionConfig,
                     ) -> ConflictDetectionResult:
    """Detect comparable disagreement for one declared quantity scope.

    A candidate is never dropped: it is either a conflict participant, an
    agreement participant, or an explicit not-compared entry. This slice emits
    unresolved conflicts only and selects no winner.
    """
    try:
        config = ConflictDetectionConfig.model_validate(config.model_dump(warnings=False))
        contract = ComparisonContract.model_validate(contract.model_dump(warnings=False))
        request = ComparisonRequest.model_validate(request.model_dump(warnings=False))
        candidates = tuple(candidates)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ConflictDetectionIntegrityError("invalid conflict-detection input") from exc
    if len(candidates) > config.maximum_candidates:
        raise ConflictDetectionLimitError("conflict detection exceeds the candidate budget")

    canonical: list[ComparableEvidence] = []
    for candidate in candidates:
        try:
            canonical.append(ComparableEvidence.model_validate(candidate.model_dump(warnings=False)))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ConflictDetectionIntegrityError("invalid comparable evidence") from exc
    identifiers = [candidate.observation_id for candidate in canonical]
    if len(set(identifiers)) != len(identifiers):
        raise ConflictDetectionIntegrityError("duplicate candidate identity in conflict detection")

    declared = [quantity for quantity in contract.quantities
                if quantity.quantity_id == request.quantity_id]
    if not declared:
        raise ConflictDetectionIntegrityError("comparison request names an undeclared quantity")
    if any(candidate.signal not in set(declared[0].signals) for candidate in canonical):
        raise ConflictDetectionIntegrityError(
            "candidate signal is not declared for the requested quantity")

    limitations: list[str] = [NO_WINNER_LIMITATION]
    if any(candidate.effective_basis == TimeBasis.GUARDIAN_RECEIPT_TIME for candidate in canonical):
        limitations.append(RECEIPT_ALIGNMENT_LIMITATION)
    if any(candidate.source_instance is None for candidate in canonical):
        limitations.append(SOURCE_INSTANCE_LIMITATION)
    correlations = [candidate.correlation_id for candidate in canonical
                    if candidate.correlation_id is not None]
    if (len({_stream(candidate) for candidate in canonical}) > 1
            and len(set(correlations)) != len(correlations)):
        limitations.append(ACQUISITION_LIMITATION)

    def result(conflicts: Sequence[StateConflict] = (), agreements: Sequence[ComparableAgreement] = (),
               not_compared: Sequence[NotComparedEvidence] = ()) -> ConflictDetectionResult:
        outcome = ConflictDetectionResult(
            conflicts=tuple(conflicts), agreements=tuple(agreements),
            not_compared=tuple(not_compared), affected_field_key=request.affected_field_key,
            quantity_id=request.quantity_id, contract_id=contract.contract_id,
            contract_version=contract.contract_version, comparison_basis=contract.comparison_basis,
            limitations=tuple(dict.fromkeys(limitations)))
        accounted = {str(identifier) for conflict in outcome.conflicts
                     for identifier in conflict.participant_evidence_ids}
        accounted |= {str(identifier) for agreement in outcome.agreements
                      for identifier in agreement.participant_evidence_ids}
        accounted |= {str(entry.observation_id) for entry in outcome.not_compared}
        expected = {str(candidate.observation_id) for candidate in canonical}
        if accounted != expected:
            raise ConflictDetectionIntegrityError("candidate coverage is incomplete")
        return outcome

    if not canonical:
        return result()

    signatures = {candidate.identity.scope_key for candidate in canonical}
    if len(signatures) > 1 or not all(_matches_request(candidate.identity, request.expected_identity)
                                      for candidate in canonical):
        conflict = _build_conflict(
            ConflictKind.IDENTITY_MISMATCH, canonical, request=request, contract=contract,
            reason="comparable_subject_identity_not_established")
        return result(conflicts=[conflict])

    valued = [candidate for candidate in canonical if candidate.value is not None]
    unvalued = tuple(NotComparedEvidence(
        observation_id=candidate.observation_id, reason="value_missing_not_zero",
        detail="missing evidence is not zero and cannot participate in a value comparison")
        for candidate in canonical if candidate.value is None)

    if len({_stream(candidate) for candidate in valued}) < 2 and len(valued) <= 1:
        return result(not_compared=unvalued + tuple(NotComparedEvidence(
            observation_id=candidate.observation_id,
            reason="comparison_requires_at_least_two_source_streams",
            detail="cross-source comparison requires evidence from at least two source streams")
            for candidate in valued))

    if len({candidate.unit for candidate in valued}) != 1:
        return result(conflicts=[_build_conflict(
            ConflictKind.UNIT_OR_SEMANTIC_MISMATCH, valued, request=request, contract=contract,
            reason="comparable_unit_not_established")], not_compared=unvalued)

    kinds = {_value_kind(candidate.value) for candidate in valued}
    if len(kinds) != 1:
        return result(conflicts=[_build_conflict(
            ConflictKind.UNIT_OR_SEMANTIC_MISMATCH, valued, request=request, contract=contract,
            reason="comparable_value_semantics_not_established")], not_compared=unvalued)

    bases = {candidate.effective_basis for candidate in valued}
    if len(bases) != 1:
        return result(conflicts=[_build_conflict(
            ConflictKind.TEMPORAL_MISALIGNMENT, valued, request=request, contract=contract,
            reason="effective_time_basis_not_comparable")], not_compared=unvalued)

    unit = next(iter({candidate.unit for candidate in valued}))
    basis = next(iter(bases))
    kind = next(iter(kinds))
    times = [candidate.effective_time for candidate in valued]
    spread = (max(times) - min(times)).total_seconds()
    tolerance = contract.maximum_alignment_seconds
    if spread > 0 and (tolerance is None or spread > tolerance):
        return result(conflicts=[_build_conflict(
            ConflictKind.TEMPORAL_MISALIGNMENT, valued, request=request, contract=contract,
            reason="declared_alignment_tolerance_missing_or_exceeded")], not_compared=unvalued)

    if kind == ValueKind.NUMBER:
        numbers = sorted({number for number in
                          (_number(candidate.value) for candidate in valued) if number is not None})
        if len(numbers) > 1:
            return result(conflicts=[_build_conflict(
                ConflictKind.VALUE_DISAGREEMENT, valued, request=request, contract=contract,
                reason="comparable_values_disagree_without_a_resolution_policy",
                quantified=(numbers[-1] - numbers[0]) if unit is not None else None, unit=unit
            )], not_compared=unvalued)
    else:
        if len(_distinct_values([candidate.value for candidate in valued])) > 1:
            return result(conflicts=[_build_conflict(
                ConflictKind.VALUE_DISAGREEMENT, valued, request=request, contract=contract,
                reason="comparable_values_disagree_without_a_resolution_policy")],
                not_compared=unvalued)
    return result(agreements=[_build_agreement(
        valued, request=request, contract=contract, agreed_value=valued[0].value,
        unit=unit, basis=basis, spread=spread)], not_compared=unvalued)




