"""Canonical observations. Receipt time never substitutes for source recording time."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


class Source(StrEnum):
    NVML = "NVML"
    SRBMINER_HTTP = "SRBMINER_HTTP"
    POOL_DATA_FROM_MINER = "POOL_DATA_FROM_MINER"
    OBSERVER = "OBSERVER"


class Quality(StrEnum):
    # Order is the accepted M3.1 primary-classification precedence.
    CORRUPTED = "CORRUPTED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    RESET_OR_DISCONTINUOUS = "RESET_OR_DISCONTINUOUS"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    DUPLICATED = "DUPLICATED"
    DELAYED = "DELAYED"
    STALE = "STALE"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"
    VALID = "VALID"


def primary_quality(conditions: tuple[Quality, ...]) -> Quality:
    return next((item for item in Quality if item in conditions), Quality.UNKNOWN)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Freshness(Contract):
    state: Literal["CURRENT", "STALE", "UNKNOWN"] = "UNKNOWN"
    evaluated_at: datetime | None = None
    basis: Literal["source_observation_time", "unavailable"] = "unavailable"
    age_seconds: float | None = None
    receipt_age_seconds: float | None = None
    stale_after_seconds: float | None = Field(default=None, ge=0)
    delay_seconds: float | None = None
    reason: str = "not_evaluated"

    @field_validator("evaluated_at")
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        return utc(value) if value is not None else None


def utc(value: datetime) -> datetime:
    """Reject ambiguous historical wall times; normalize only aware timestamps."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("authoritative M3 timestamps must be timezone-aware")
    return value.astimezone(UTC)


class RuntimeObservation(Contract):
    observation_id: UUID = Field(default_factory=uuid4)
    source: Source
    source_instance: str | None = Field(default=None, min_length=1, max_length=1024)
    signal: str = Field(min_length=1, max_length=128)
    value: JsonValue = None
    unit: str | None = Field(default=None, min_length=1, max_length=64)
    event_time: datetime | None = None
    observation_time: datetime | None = None
    ingestion_time: datetime
    processing_time: datetime | None = None
    quality: Quality = Quality.UNKNOWN
    quality_conditions: tuple[Quality, ...] = ()
    quality_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    freshness: Freshness = Field(default_factory=Freshness)
    guardian_session_id: str | None = Field(default=None, min_length=1, max_length=128)
    correlation_id: UUID
    schema_version: Literal["m3.1.runtime-observation.v1"] = "m3.1.runtime-observation.v1"
    provenance: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("event_time", "observation_time", "ingestion_time", "processing_time")
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        return utc(value) if value is not None else None

    @model_validator(mode="after")
    def classify(self) -> "RuntimeObservation":
        conditions = set(self.quality_conditions) | {self.quality}
        if self.value is None:
            conditions.add(Quality.MISSING)
        if self.source_instance is None:
            conditions.add(Quality.UNKNOWN)
        ordered = tuple(q for q in Quality if q in conditions)
        object.__setattr__(self, "quality_conditions", ordered)
        object.__setattr__(self, "quality", primary_quality(ordered))
        return self


def with_conditions(observation: RuntimeObservation, *conditions: Quality,
                    **changes: object) -> RuntimeObservation:
    data = observation.model_dump()
    data.update(changes)
    data["quality_conditions"] = (*observation.quality_conditions, *conditions)
    return RuntimeObservation.model_validate(data)
