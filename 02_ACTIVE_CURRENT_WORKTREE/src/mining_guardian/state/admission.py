"""M3.2-S3 temporal admission: quality, clock, age, window and as-of availability.

Every field is evaluated against an explicit caller-supplied aware-UTC
``state_reference_time`` (``T``) and the field contract's finite ``(T - W, T]``
window. Source recording time and Guardian receipt time stay distinct: receipt
time never substitutes for a missing source recording time, ages are reported
without clamping, and recorded M3.1 quality and freshness are preserved rather
than rewritten.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from mining_guardian.observability.models import Freshness, Quality, RuntimeObservation, utc
from mining_guardian.state.contracts import FieldEvidenceContract, Name, StateContract, TimeBasis

ADMISSION_METHOD = "m3.2.temporal-admission"
ADMISSION_METHOD_VERSION = "v1"
RECEIPT_BASIS_LIMITATION = "receipt_basis_does_not_establish_source_measurement_age"
PROCESSING_TIME_LIMITATION = "unknown_processing_time_does_not_prove_historical_consumption"
CONTEXT_LIMITATION = "retained_as_descriptive_context_not_current_value"


class AdmissionError(RuntimeError):
    """Base class for explicit temporal-admission failures."""


class AdmissionIntegrityError(AdmissionError):
    """Supplied evidence is not a canonical, unambiguous evidence set."""


class AdmissionLimitError(AdmissionError):
    """A declared bounded-work ceiling was exceeded."""


class AdmissionOutcome(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    CONTEXT_ONLY = "CONTEXT_ONLY"
    EXCLUDED = "EXCLUDED"


class AdmissionFlag(StrEnum):
    """Recorded admission facts; the outcome is derived from these, never hidden."""

    RECEIVED_AFTER_REFERENCE_TIME = "received_after_state_reference_time"
    CANONICALIZED_AFTER_REFERENCE_TIME = "canonicalized_after_state_reference_time"
    SOURCE_CLOCK_AFTER_RECEIPT = "source_clock_after_receipt"
    SOURCE_TIME_AFTER_REFERENCE_TIME = "source_time_after_state_reference_time"
    SOURCE_TIME_AT_OR_BEFORE_WINDOW_START = "source_time_at_or_before_window_start"
    RECEIPT_TIME_AT_OR_BEFORE_WINDOW_START = "receipt_time_at_or_before_window_start"
    SOURCE_CLOCK_UNAVAILABLE = "source_clock_unavailable"
    PROCESSING_TIME_UNKNOWN = "processing_time_unknown"
    VALUE_MISSING = "value_missing"
    SOURCE_UNAVAILABLE = "source_unavailable"
    STALE_RECORDED = "stale_recorded_by_m3_1"
    QUALITY_NOT_ADMISSIBLE = "quality_not_admissible_under_field_contract"
    RECORDED_FRESHNESS_NOT_EVALUATED = "recorded_freshness_not_evaluated"


_EXCLUSION_FLAGS = frozenset({
    AdmissionFlag.RECEIVED_AFTER_REFERENCE_TIME,
    AdmissionFlag.CANONICALIZED_AFTER_REFERENCE_TIME,
    AdmissionFlag.SOURCE_CLOCK_AFTER_RECEIPT,
    AdmissionFlag.SOURCE_TIME_AFTER_REFERENCE_TIME,
    AdmissionFlag.SOURCE_TIME_AT_OR_BEFORE_WINDOW_START,
    AdmissionFlag.RECEIPT_TIME_AT_OR_BEFORE_WINDOW_START,
    AdmissionFlag.VALUE_MISSING,
    AdmissionFlag.SOURCE_UNAVAILABLE,
    AdmissionFlag.QUALITY_NOT_ADMISSIBLE,
})
_CONTEXT_FLAGS = frozenset({AdmissionFlag.STALE_RECORDED})
_HISTORY_FLAGS = frozenset({AdmissionFlag.STALE_RECORDED})
_FLAG_ORDER = {flag: index for index, flag in enumerate(AdmissionFlag)}


def derive_outcome(flags: tuple[AdmissionFlag, ...], basis: TimeBasis) -> AdmissionOutcome:
    """Deterministic outcome precedence; every applicable fact remains recorded."""
    recorded = frozenset(flags)
    if recorded & _EXCLUSION_FLAGS:
        return AdmissionOutcome.EXCLUDED
    if recorded & _CONTEXT_FLAGS:
        return AdmissionOutcome.CONTEXT_ONLY
    if (basis == TimeBasis.SOURCE_OBSERVATION_TIME
            and AdmissionFlag.SOURCE_CLOCK_UNAVAILABLE in recorded):
        return AdmissionOutcome.CONTEXT_ONLY
    return AdmissionOutcome.ELIGIBLE


class AdmissionAssessment(StateContract):
    """One admission decision with all recorded clocks and M3.1 semantics preserved."""

    observation_id: UUID
    outcome: AdmissionOutcome
    flags: tuple[AdmissionFlag, ...] = ()
    reasons: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = ()
    temporal_basis: TimeBasis
    window_start: datetime
    window_end: datetime
    source_age_seconds: float | None = None
    receipt_age_seconds: float
    physical_age_known: bool
    eligible_for_current: bool
    eligible_for_history: bool
    input_quality: Quality
    input_quality_conditions: tuple[Quality, ...]
    recorded_freshness: Freshness
    field_contract_id: Name
    field_contract_version: Name
    method_name: Name = ADMISSION_METHOD
    method_version: Name = ADMISSION_METHOD_VERSION

    @field_validator("window_start", "window_end")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        return utc(value)

    @property
    def temporal_assessment(self) -> str:
        return self.outcome.value

    @property
    def primary_reason(self) -> str:
        return self.reasons[0]

    @model_validator(mode="after")
    def assessment_is_self_consistent(self) -> Self:
        if self.window_start >= self.window_end:
            raise ValueError("admission window must be finite and increasing")
        if len(set(self.flags)) != len(self.flags):
            raise ValueError("duplicate admission flag")
        if self.outcome != derive_outcome(self.flags, self.temporal_basis):
            raise ValueError("admission outcome disagrees with recorded flags")
        eligible = self.outcome == AdmissionOutcome.ELIGIBLE
        if self.eligible_for_current != eligible:
            raise ValueError("current eligibility disagrees with the admission outcome")
        if self.eligible_for_history != (eligible or bool(frozenset(self.flags) & _HISTORY_FLAGS)):
            raise ValueError("historical eligibility disagrees with recorded flags")
        if self.physical_age_known != (self.source_age_seconds is not None):
            raise ValueError("physical age availability disagrees with the source clock")
        if (eligible and self.temporal_basis == TimeBasis.SOURCE_OBSERVATION_TIME
                and not self.physical_age_known):
            raise ValueError("source-time eligibility requires a recorded source clock")
        if (AdmissionFlag.PROCESSING_TIME_UNKNOWN in self.flags
                and PROCESSING_TIME_LIMITATION not in self.limitations):
            raise ValueError("unknown processing time must retain its explicit limitation")
        return self


class AdmissionConfig(StateContract):
    """Explicit bounded-work configuration; there is no hidden operational default."""

    maximum_observations: int = Field(gt=0)


def admission_window(state_reference_time: datetime,
                     field_contract: FieldEvidenceContract) -> tuple[datetime, datetime]:
    """Return the field's exclusive-lower, inclusive-upper support interval."""
    try:
        reference = utc(state_reference_time)
        window_start = reference - timedelta(seconds=field_contract.window_seconds)
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        raise AdmissionError("admission window cannot be established from the supplied input") from exc
    return window_start, reference


def _assess(record: RuntimeObservation, window_start: datetime, window_end: datetime,
            contract: FieldEvidenceContract) -> AdmissionAssessment:
    basis = contract.temporal_basis
    conditions = tuple(record.quality_conditions)
    observation_time = record.observation_time
    collected: set[AdmissionFlag] = set()

    if record.ingestion_time > window_end:
        collected.add(AdmissionFlag.RECEIVED_AFTER_REFERENCE_TIME)
    elif record.ingestion_time <= window_start:
        collected.add(AdmissionFlag.RECEIPT_TIME_AT_OR_BEFORE_WINDOW_START)

    if record.processing_time is None:
        collected.add(AdmissionFlag.PROCESSING_TIME_UNKNOWN)
    elif record.processing_time > window_end:
        collected.add(AdmissionFlag.CANONICALIZED_AFTER_REFERENCE_TIME)

    if observation_time is None:
        collected.add(AdmissionFlag.SOURCE_CLOCK_UNAVAILABLE)
    else:
        if observation_time > record.ingestion_time:
            collected.add(AdmissionFlag.SOURCE_CLOCK_AFTER_RECEIPT)
        if observation_time > window_end:
            collected.add(AdmissionFlag.SOURCE_TIME_AFTER_REFERENCE_TIME)
        elif observation_time <= window_start:
            collected.add(AdmissionFlag.SOURCE_TIME_AT_OR_BEFORE_WINDOW_START)

    if record.value is None:
        collected.add(AdmissionFlag.VALUE_MISSING)
    if Quality.SOURCE_UNAVAILABLE in conditions:
        collected.add(AdmissionFlag.SOURCE_UNAVAILABLE)
    if any(condition not in contract.admissible_quality for condition in conditions):
        collected.add(AdmissionFlag.QUALITY_NOT_ADMISSIBLE)
    if Quality.STALE in conditions or record.freshness.state == "STALE":
        collected.add(AdmissionFlag.STALE_RECORDED)
    if record.freshness.state == "UNKNOWN":
        collected.add(AdmissionFlag.RECORDED_FRESHNESS_NOT_EVALUATED)

    ordered = tuple(sorted(collected, key=lambda flag: _FLAG_ORDER[flag]))
    outcome = derive_outcome(ordered, basis)
    physical_age_known = observation_time is not None
    limitations: list[str] = []
    if AdmissionFlag.PROCESSING_TIME_UNKNOWN in collected:
        limitations.append(PROCESSING_TIME_LIMITATION)
    if not physical_age_known:
        limitations.append(RECEIPT_BASIS_LIMITATION)
    if basis == TimeBasis.GUARDIAN_RECEIPT_TIME:
        limitations.append("receipt_time_is_not_a_source_event_interval")
    if outcome == AdmissionOutcome.CONTEXT_ONLY:
        limitations.append(CONTEXT_LIMITATION)
    return AdmissionAssessment(
        observation_id=record.observation_id,
        outcome=outcome,
        flags=ordered,
        reasons=(tuple(flag.value for flag in ordered)
                 or ("all_declared_admission_conditions_satisfied",)),
        limitations=tuple(dict.fromkeys(limitations)),
        temporal_basis=basis,
        window_start=window_start,
        window_end=window_end,
        source_age_seconds=(None if observation_time is None
                            else (window_end - observation_time).total_seconds()),
        receipt_age_seconds=(window_end - record.ingestion_time).total_seconds(),
        physical_age_known=physical_age_known,
        eligible_for_current=outcome == AdmissionOutcome.ELIGIBLE,
        eligible_for_history=(outcome == AdmissionOutcome.ELIGIBLE
                              or bool(collected & _HISTORY_FLAGS)),
        input_quality=record.quality,
        input_quality_conditions=record.quality_conditions,
        recorded_freshness=record.freshness,
        field_contract_id=contract.contract_id,
        field_contract_version=contract.contract_version,
    )


def assess_admission(records: Sequence[RuntimeObservation], state_reference_time: datetime,
                     field_contract: FieldEvidenceContract,
                     config: AdmissionConfig) -> tuple[AdmissionAssessment, ...]:
    """Assess a bounded evidence set against one explicit as-of instant.

    Ages are reported exactly as computed and are never clamped; evidence
    received after ``T`` is excluded rather than treated as fresh; a null source
    recording time stays null and never becomes the receipt time.
    """
    try:
        config = AdmissionConfig.model_validate(config.model_dump(warnings=False))
        contract = FieldEvidenceContract.model_validate(field_contract.model_dump(warnings=False))
        records = tuple(records)
    except (AttributeError, TypeError, ValueError) as exc:
        raise AdmissionIntegrityError("invalid temporal-admission input") from exc
    if len(records) > config.maximum_observations:
        raise AdmissionLimitError("temporal admission exceeds the observation budget")
    window_start, window_end = admission_window(state_reference_time, contract)
    canonical: list[RuntimeObservation] = []
    for record in records:
        try:
            canonical.append(RuntimeObservation.model_validate(record.model_dump(warnings=False)))
        except (AttributeError, TypeError, ValueError) as exc:
            raise AdmissionIntegrityError("invalid canonical runtime observation") from exc
    identifiers = [record.observation_id for record in canonical]
    if len(set(identifiers)) != len(identifiers):
        raise AdmissionIntegrityError("duplicate evidence identity in temporal admission")
    assessments = tuple(_assess(record, window_start, window_end, contract) for record in canonical)
    return tuple(sorted(assessments, key=lambda assessment: str(assessment.observation_id)))

