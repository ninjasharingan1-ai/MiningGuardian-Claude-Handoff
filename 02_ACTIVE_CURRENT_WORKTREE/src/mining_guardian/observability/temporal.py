"""Explicit per-source/signal freshness; missing source clocks stay unknown."""

import time
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import Field

from .models import Contract, Freshness, Quality, RuntimeObservation, Source, utc, with_conditions


class Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


class FreshnessRule(Contract):
    source: Source
    signal: str = Field(min_length=1)
    stale_after_seconds: float = Field(ge=0)
    delayed_after_seconds: float | None = Field(default=None, ge=0)


def elapsed(start: float, monotonic: Callable[[], float]) -> float:
    duration = monotonic() - start
    if duration < 0:
        raise ValueError("monotonic clock regressed")
    return duration


def evaluate_freshness(record: RuntimeObservation, now: datetime,
                       rules: tuple[FreshnessRule, ...] = ()) -> RuntimeObservation:
    now = utc(now)
    matches = [r for r in rules if r.source == record.source and r.signal == record.signal]
    if len(matches) > 1:
        raise ValueError("ambiguous freshness configuration")
    rule = matches[0] if matches else None
    receipt_age = (now - record.ingestion_time).total_seconds()
    age = None if record.observation_time is None else (now - record.observation_time).total_seconds()
    # Delay requires an explicit underlying-event clock (handoff section 19).
    delay = None if record.event_time is None else (record.ingestion_time - record.event_time).total_seconds()
    future = (receipt_age < 0 or (age is not None and age < 0) or (delay is not None and delay < 0)
              or (record.observation_time is not None and record.observation_time > record.ingestion_time)
              or (record.event_time is not None and record.observation_time is not None and record.event_time > record.observation_time))
    conditions: list[Quality] = []
    state = "UNKNOWN"
    reason = "source_recording_time_unavailable" if age is None else "no_matching_rule"
    if future:
        conditions.append(Quality.OUT_OF_RANGE)
        reason = "clock_order_inconsistent"
    elif rule is not None and age is not None:
        state = "STALE" if age > rule.stale_after_seconds else "CURRENT"
        reason = "configured_source_signal_age"
        if state == "STALE":
            conditions.append(Quality.STALE)
    if not future and rule is not None and delay is not None and rule.delayed_after_seconds is not None and delay > rule.delayed_after_seconds:
        conditions.append(Quality.DELAYED)
    freshness = Freshness.model_validate({
        "state": state, "evaluated_at": now, "age_seconds": age,
        "receipt_age_seconds": receipt_age, "delay_seconds": delay,
        "basis": "unavailable" if age is None else "source_observation_time",
        "stale_after_seconds": None if rule is None else rule.stale_after_seconds,
        "reason": reason,
    })
    return with_conditions(record, *conditions, freshness=freshness)
