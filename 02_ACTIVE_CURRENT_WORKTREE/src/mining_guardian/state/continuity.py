"""M3.2-S3 analytical continuity segmentation.

A continuity segment is an analytical evidence group, never a claim about a
miner process incarnation. Boundaries are derived from supplied evidence and an
explicit versioned contract; a counter or uptime decrease alone therefore never
asserts a restart, negative deltas are never clamped, rollover is never
assumed, and derived arithmetic is scoped to, never across, a segment.

Only the persisted per-record attributes of the supplied evidence are used.
M3.1's process-local continuity tracker is deliberately not imported and is
never replay authority.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from mining_guardian.observability.models import Quality, RuntimeObservation, Source, utc
from mining_guardian.state.contracts import Name, StateContract, TimeBasis
from mining_guardian.state.subjects import IdentityResolution, deterministic_digest

CONTINUITY_METHOD = "m3.2.continuity-segmentation"
CONTINUITY_METHOD_VERSION = "v1"


class ContinuityError(RuntimeError):
    """Base class for explicit continuity-segmentation failures."""


class ContinuityIntegrityError(ContinuityError):
    """Supplied evidence is not a canonical, unambiguous evidence set."""


class ContinuityLimitError(ContinuityError):
    """A declared bounded-work ceiling was exceeded."""


class CrossSegmentError(ContinuityError):
    """Derived arithmetic was requested across an analytical segment boundary."""


class BreakReason(StrEnum):
    """Every boundary reason stays traceable; none of them asserts a restart."""

    SEGMENT_START = "SEGMENT_START"
    EXPLICIT_INCARNATION_CHANGE = "EXPLICIT_INCARNATION_CHANGE"
    COUNTER_DECREASE_OR_RESET = "COUNTER_DECREASE_OR_RESET"
    RECORDED_DISCONTINUITY = "RECORDED_DISCONTINUITY"
    SUBJECT_CHANGE = "SUBJECT_CHANGE"
    WORKLOAD_CHANGE = "WORKLOAD_CHANGE"
    ALGORITHM_CHANGE = "ALGORITHM_CHANGE"
    COUNTER_SEMANTICS_CHANGE = "COUNTER_SEMANTICS_CHANGE"
    EXCESSIVE_GAP = "EXCESSIVE_GAP"
    UNRESOLVED_ORDERING_CONFLICT = "UNRESOLVED_ORDERING_CONFLICT"
    UNRESOLVED_IDENTITY_CONFLICT = "UNRESOLVED_IDENTITY_CONFLICT"


_BREAK_ORDER = {reason: index for index, reason in enumerate(BreakReason)}


class IncarnationStatus(StrEnum):
    PROVEN = "PROVEN"
    UNKNOWN = "UNKNOWN"


class CounterSemantics(StrEnum):
    CUMULATIVE = "CUMULATIVE"
    NOT_CUMULATIVE = "NOT_CUMULATIVE"


class ContinuityContract(StateContract):
    """Explicit, versioned segmentation contract derived from a field contract."""

    contract_id: Name
    contract_version: Name
    continuity_rule: Name
    ordering_basis: TimeBasis
    maximum_gap_seconds: float | None = None
    counter_semantics: CounterSemantics | None = None
    honor_recorded_discontinuity: bool = False
    minimum_segment_samples: int = Field(ge=1)
    minimum_segment_elapsed_seconds: float = Field(ge=0)

    @model_validator(mode="after")
    def explicit_limits(self) -> Self:
        if self.maximum_gap_seconds is not None and self.maximum_gap_seconds <= 0:
            raise ValueError("declared maximum gap must be positive")
        return self


class ScopedObservation(StateContract):
    """One observation with its resolved identity and any proven incarnation evidence."""

    record: RuntimeObservation
    identity: IdentityResolution
    incarnation: str | None = None

    @model_validator(mode="after")
    def identity_belongs_to_record(self) -> Self:
        if self.identity.observation_id != self.record.observation_id:
            raise ValueError("scoped identity belongs to a different observation")
        if self.incarnation is not None and not self.incarnation.strip():
            raise ValueError("proven incarnation evidence cannot be blank")
        return self


class ContinuityConfig(StateContract):
    """Explicit bounded-work configuration; there is no hidden operational default."""

    maximum_observations: int = Field(gt=0)


class SegmentBoundary(StateContract):
    """Why a segment started, with every observed cause retained."""

    segment_id: str
    reasons: tuple[BreakReason, ...] = Field(min_length=1)
    observation_id: UUID
    previous_observation_id: UUID | None = None
    elapsed_seconds: float | None = None
    evidence: tuple[str, ...] = ()
    restart_asserted: Literal[False] = False


class UnassignedEvidence(StateContract):
    """Evidence retained outside every segment with an explicit reason."""

    observation_id: UUID
    reason: BreakReason
    detail: str


class AnalyticalSegment(StateContract):
    """One analytical evidence group with full provenance and arithmetic scope."""

    segment_id: str
    segment_index: int = Field(ge=0)
    ordering_basis: TimeBasis
    source: Source
    source_instance: str | None = None
    signal: Name
    subject_id: str | None = None
    workload_id: str | None = None
    algorithm_id: str | None = None
    identity_signature: str
    anchor_observation_id: UUID
    observation_ids: tuple[UUID, ...] = Field(min_length=1)
    start_time: datetime
    end_time: datetime
    elapsed_seconds: float = Field(ge=0)
    boundary: SegmentBoundary
    incarnation_status: IncarnationStatus
    proven_incarnation: str | None = None
    minimum_segment_samples: int = Field(ge=1)
    minimum_segment_elapsed_seconds: float = Field(ge=0)
    evidence_sufficient_for_derivation: bool
    limitations: tuple[str, ...] = ()
    continuity_contract_id: Name
    continuity_contract_version: Name
    continuity_rule: Name
    method_name: Name = CONTINUITY_METHOD
    method_version: Name = CONTINUITY_METHOD_VERSION

    @field_validator("start_time", "end_time")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        return utc(value)

    @model_validator(mode="after")
    def provenance_is_coherent(self) -> Self:
        if self.start_time > self.end_time:
            raise ValueError("segment interval is reversed")
        if self.observation_ids[0] != self.anchor_observation_id:
            raise ValueError("segment anchor is not the first ordered observation")
        if self.boundary.segment_id != self.segment_id:
            raise ValueError("segment boundary belongs to a different segment")
        if self.boundary.observation_id != self.anchor_observation_id:
            raise ValueError("segment boundary does not describe this anchor")
        if self.incarnation_status == IncarnationStatus.PROVEN and self.proven_incarnation is None:
            raise ValueError("proven incarnation requires proven evidence")
        if self.incarnation_status == IncarnationStatus.UNKNOWN and self.proven_incarnation is not None:
            raise ValueError("unknown incarnation cannot carry proven evidence")
        return self


class ContinuityResult(StateContract):
    """Deterministic segments, every boundary, and every unassigned observation."""

    segments: tuple[AnalyticalSegment, ...] = ()
    boundaries: tuple[SegmentBoundary, ...] = ()
    unassigned: tuple[UnassignedEvidence, ...] = ()
    contract_id: Name
    contract_version: Name
    continuity_rule: Name
    ordering_basis: TimeBasis
    method_name: Name = CONTINUITY_METHOD
    method_version: Name = CONTINUITY_METHOD_VERSION

    @model_validator(mode="after")
    def complete_evidence_accounting(self) -> Self:
        assigned = [identifier for segment in self.segments for identifier in segment.observation_ids]
        if len(set(assigned)) != len(assigned):
            raise ValueError("one observation cannot belong to two analytical segments")
        if set(assigned) & {item.observation_id for item in self.unassigned}:
            raise ValueError("one observation cannot be both assigned and unassigned")
        if [segment.segment_id for segment in self.segments] != [b.segment_id for b in self.boundaries]:
            raise ValueError("segment inventory and boundary inventory disagree")
        if [segment.segment_index for segment in self.segments] != list(range(len(self.segments))):
            raise ValueError("segment indexes are not a dense deterministic sequence")
        return self


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _ordering_time(record: RuntimeObservation, basis: TimeBasis) -> datetime | None:
    if basis == TimeBasis.SOURCE_OBSERVATION_TIME:
        return record.observation_time
    return record.ingestion_time


def _break_reasons(previous: ScopedObservation, current: ScopedObservation, gap: float,
                   contract: ContinuityContract) -> tuple[tuple[BreakReason, ...], tuple[str, ...]]:
    """Collect every applicable boundary condition; none of them asserts a restart."""
    reasons: list[BreakReason] = []
    evidence: list[str] = []
    before, after = previous.identity, current.identity
    for label, first, second in (("subject", before.subject, after.subject),
                                 ("workload", before.workload, after.workload),
                                 ("algorithm", before.algorithm, after.algorithm)):
        if (first.status.value, first.resolved_id) != (second.status.value, second.resolved_id):
            reasons.append(BreakReason[f"{label.upper()}_CHANGE"])
            evidence.append(f"{label}_identity_basis_changed")
    if (previous.incarnation is not None and current.incarnation is not None
            and previous.incarnation != current.incarnation):
        reasons.append(BreakReason.EXPLICIT_INCARNATION_CHANGE)
        evidence.append("explicit_source_incarnation_changed_without_restart_claim")
    if contract.counter_semantics is not None:
        if previous.record.unit != current.record.unit:
            reasons.append(BreakReason.COUNTER_SEMANTICS_CHANGE)
            evidence.append("declared_counter_unit_changed")
        former, latter = _number(previous.record.value), _number(current.record.value)
        if (former is None) != (latter is None):
            reasons.append(BreakReason.COUNTER_SEMANTICS_CHANGE)
            evidence.append("declared_counter_value_semantics_changed")
        elif (contract.counter_semantics == CounterSemantics.CUMULATIVE
              and former is not None and latter is not None and latter < former):
            reasons.append(BreakReason.COUNTER_DECREASE_OR_RESET)
            evidence.append("cumulative_value_decreased_does_not_prove_restart")
    if (contract.honor_recorded_discontinuity
            and Quality.RESET_OR_DISCONTINUOUS in current.record.quality_conditions):
        reasons.append(BreakReason.RECORDED_DISCONTINUITY)
        evidence.append("recorded_reset_or_discontinuity_flag_honored_by_contract")
    if Quality.OUT_OF_ORDER in current.record.quality_conditions:
        reasons.append(BreakReason.UNRESOLVED_ORDERING_CONFLICT)
        evidence.append("recorded_source_ordering_regression_without_accepted_proof")
    if contract.maximum_gap_seconds is not None and gap > contract.maximum_gap_seconds:
        reasons.append(BreakReason.EXCESSIVE_GAP)
        evidence.append("configured_maximum_gap_exceeded")
    ordered = tuple(sorted(set(reasons), key=lambda reason: _BREAK_ORDER[reason]))
    return ordered, tuple(dict.fromkeys(evidence))


def _build_segment(stream: tuple[str, str, str], members: Sequence[tuple[datetime, ScopedObservation]],
                   segment_index: int, reasons: tuple[BreakReason, ...],
                   previous_id: UUID | None, gap: float | None, evidence: tuple[str, ...],
                   contract: ContinuityContract) -> AnalyticalSegment:
    source_value, source_instance, signal = stream
    anchor_time, anchor = members[0]
    end_time = members[-1][0]
    observation_ids = tuple(item.record.observation_id for _, item in members)
    elapsed = (end_time - anchor_time).total_seconds()
    identity = anchor.identity
    incarnations = {item.incarnation for _, item in members}
    proven_incarnation = next(iter(incarnations)) if len(incarnations) == 1 else None
    segment_id = deterministic_digest("continuity-segment", (
        contract.contract_id, contract.contract_version, contract.continuity_rule,
        contract.ordering_basis.value, source_value, source_instance, signal,
        identity.scope_key, str(anchor.record.observation_id),
        *(str(identifier) for identifier in observation_ids),
    ))
    sufficient = (len(observation_ids) >= contract.minimum_segment_samples
                  and elapsed >= contract.minimum_segment_elapsed_seconds)
    limitations: list[str] = []
    if source_instance == "":
        limitations.append("source_instance_unavailable")
    if contract.maximum_gap_seconds is None:
        limitations.append("gap_break_not_configured")
    if contract.counter_semantics is None:
        limitations.append("counter_semantics_not_declared")
    if contract.ordering_basis == TimeBasis.GUARDIAN_RECEIPT_TIME:
        limitations.append("receipt_basis_is_not_a_source_event_interval")
    if any(Quality.DUPLICATED in item.record.quality_conditions for _, item in members):
        limitations.append("contains_recorded_duplicate_evidence")
    if (not contract.honor_recorded_discontinuity
            and any(Quality.RESET_OR_DISCONTINUOUS in item.record.quality_conditions
                    for _, item in members)):
        limitations.append("recorded_reset_flag_not_honored_by_contract")
    if not sufficient:
        limitations.append("segment_below_declared_derivation_minimum")
    return AnalyticalSegment(
        segment_id=segment_id,
        segment_index=segment_index,
        ordering_basis=contract.ordering_basis,
        source=Source(source_value),
        source_instance=source_instance or None,
        signal=signal,
        subject_id=identity.subject.resolved_id,
        workload_id=identity.workload.resolved_id,
        algorithm_id=identity.algorithm.resolved_id,
        identity_signature=identity.scope_key,
        anchor_observation_id=anchor.record.observation_id,
        observation_ids=observation_ids,
        start_time=anchor_time,
        end_time=end_time,
        elapsed_seconds=elapsed,
        boundary=SegmentBoundary(
            segment_id=segment_id, reasons=reasons,
            observation_id=anchor.record.observation_id, previous_observation_id=previous_id,
            elapsed_seconds=gap, evidence=evidence,
        ),
        incarnation_status=(IncarnationStatus.PROVEN if proven_incarnation is not None
                            else IncarnationStatus.UNKNOWN),
        proven_incarnation=proven_incarnation,
        minimum_segment_samples=contract.minimum_segment_samples,
        minimum_segment_elapsed_seconds=contract.minimum_segment_elapsed_seconds,
        evidence_sufficient_for_derivation=sufficient,
        limitations=tuple(dict.fromkeys(limitations)),
        continuity_contract_id=contract.contract_id,
        continuity_contract_version=contract.contract_version,
        continuity_rule=contract.continuity_rule,
    )


def segment_evidence(observations: Sequence[ScopedObservation], contract: ContinuityContract,
                     config: ContinuityConfig) -> ContinuityResult:
    """Derive deterministic analytical segments from scoped, orderable evidence.

    Ordering uses only the declared basis. Evidence whose basis time is
    unavailable, or whose declared identity cannot be resolved, is retained as
    explicitly unassigned rather than silently placed by receipt order or row
    position.
    """
    try:
        config = ContinuityConfig.model_validate(config.model_dump(warnings=False))
        contract = ContinuityContract.model_validate(contract.model_dump(warnings=False))
        observations = tuple(observations)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ContinuityIntegrityError("invalid continuity-segmentation input") from exc
    if len(observations) > config.maximum_observations:
        raise ContinuityLimitError("continuity segmentation exceeds the observation budget")

    canonical: list[ScopedObservation] = []
    for item in observations:
        try:
            canonical.append(ScopedObservation.model_validate(item.model_dump(warnings=False)))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ContinuityIntegrityError("invalid scoped observation") from exc
    identifiers = [item.record.observation_id for item in canonical]
    if len(set(identifiers)) != len(identifiers):
        raise ContinuityIntegrityError("duplicate evidence identity in continuity segmentation")

    buckets: dict[tuple[str, str, str], list[tuple[datetime, ScopedObservation]]] = {}
    unassigned: list[UnassignedEvidence] = []
    for item in canonical:
        ordering_time = _ordering_time(item.record, contract.ordering_basis)
        if ordering_time is None:
            unassigned.append(UnassignedEvidence(
                observation_id=item.record.observation_id,
                reason=BreakReason.UNRESOLVED_ORDERING_CONFLICT,
                detail="ordering_basis_time_unavailable"))
            continue
        unresolved = item.identity.unresolved_components
        if unresolved:
            unassigned.append(UnassignedEvidence(
                observation_id=item.record.observation_id,
                reason=BreakReason.UNRESOLVED_IDENTITY_CONFLICT,
                detail="unresolved_identity_components:" + ",".join(unresolved)))
            continue
        stream = (item.record.source.value, item.record.source_instance or "", item.record.signal)
        buckets.setdefault(stream, []).append((ordering_time, item))

    segments: list[AnalyticalSegment] = []
    boundaries: list[SegmentBoundary] = []
    for stream in sorted(buckets):
        ordered = sorted(buckets[stream],
                         key=lambda pair: (pair[0], pair[1].record.ingestion_time,
                                           str(pair[1].record.observation_id)))
        members: list[tuple[datetime, ScopedObservation]] = []
        start_reasons: tuple[BreakReason, ...] = (BreakReason.SEGMENT_START,)
        start_previous: UUID | None = None
        start_gap: float | None = None
        start_evidence: tuple[str, ...] = ()
        for ordering_time, item in ordered:
            if members:
                previous_time, previous_item = members[-1]
                gap = (ordering_time - previous_time).total_seconds()
                reasons, evidence = _break_reasons(previous_item, item, gap, contract)
                if reasons:
                    segment = _build_segment(stream, members, len(segments), start_reasons,
                                             start_previous, start_gap, start_evidence, contract)
                    segments.append(segment)
                    boundaries.append(segment.boundary)
                    members = []
                    start_reasons = reasons
                    start_previous = previous_item.record.observation_id
                    start_gap = gap
                    start_evidence = evidence
            members.append((ordering_time, item))
        if members:
            segment = _build_segment(stream, members, len(segments), start_reasons,
                                     start_previous, start_gap, start_evidence, contract)
            segments.append(segment)
            boundaries.append(segment.boundary)

    return ContinuityResult(
        segments=tuple(segments),
        boundaries=tuple(boundaries),
        unassigned=tuple(sorted(unassigned, key=lambda entry: str(entry.observation_id))),
        contract_id=contract.contract_id,
        contract_version=contract.contract_version,
        continuity_rule=contract.continuity_rule,
        ordering_basis=contract.ordering_basis,
    )


def segment_index(result: ContinuityResult) -> Mapping[str, str]:
    """Deterministic observation-to-segment lookup; the arithmetic scope of record."""
    return {str(identifier): segment.segment_id
            for segment in result.segments for identifier in segment.observation_ids}


def require_shared_segment(result: ContinuityResult, first: UUID, second: UUID) -> str:
    """Return the shared segment identity, or refuse cross-segment arithmetic."""
    index = segment_index(result)
    first_segment, second_segment = index.get(str(first)), index.get(str(second))
    if first_segment is None or second_segment is None:
        raise CrossSegmentError("evidence is not assigned to an analytical segment")
    if first_segment != second_segment:
        raise CrossSegmentError("derived arithmetic across a segment boundary is not permitted")
    return first_segment





