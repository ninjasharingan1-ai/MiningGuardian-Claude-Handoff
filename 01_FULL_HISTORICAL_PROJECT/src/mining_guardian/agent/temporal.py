"""Deterministic temporal semantics for M2.1.1 agent context."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class ObservationOrigin(StrEnum):
    """Where the current observation came from."""

    LIVE_PROBE = "live_probe"
    PERSISTED = "persisted"


class FreshnessLevel(StrEnum):
    """Deterministic age classification independent of observation origin."""

    FRESH = "fresh"
    RECENT = "recent"
    STALE = "stale"
    UNKNOWN = "unknown"


class GuardianSessionStatus(StrEnum):
    """Lifecycle of a Mining Guardian observe session."""

    ACTIVE = "active"
    ENDED = "ended"
    UNKNOWN = "unknown"


class MinerReachability(StrEnum):
    """Result of a direct miner API reachability probe."""

    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"


def ensure_utc(value: datetime | None) -> datetime | None:
    """Return a timezone-aware UTC datetime, treating legacy naive values as UTC."""

    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def age_seconds(timestamp: datetime | None, now: datetime) -> float | None:
    """Return non-negative sample age in seconds."""

    timestamp_utc = ensure_utc(timestamp)
    now_utc = ensure_utc(now)
    if timestamp_utc is None or now_utc is None:
        return None
    return max(0.0, (now_utc - timestamp_utc).total_seconds())


@dataclass(frozen=True)
class FreshnessPolicy:
    """Central deterministic freshness thresholds used by agent context."""

    fresh_max_age_seconds: float = 30.0
    recent_max_age_seconds: float = 120.0

    def __post_init__(self) -> None:
        if self.fresh_max_age_seconds < 0:
            raise ValueError("fresh_max_age_seconds must be >= 0")
        if self.recent_max_age_seconds < self.fresh_max_age_seconds:
            raise ValueError(
                "recent_max_age_seconds must be >= fresh_max_age_seconds"
            )

    def classify_age(self, age: float | None) -> FreshnessLevel:
        """Classify an already-computed age."""

        if age is None:
            return FreshnessLevel.UNKNOWN
        if age <= self.fresh_max_age_seconds:
            return FreshnessLevel.FRESH
        if age <= self.recent_max_age_seconds:
            return FreshnessLevel.RECENT
        return FreshnessLevel.STALE

    def classify_timestamp(
        self,
        timestamp: datetime | None,
        *,
        now: datetime,
    ) -> FreshnessLevel:
        """Classify a sample timestamp relative to an explicit reference time."""

        return self.classify_age(age_seconds(timestamp, now))

    @staticmethod
    def conservative_overall(
        *levels: FreshnessLevel,
    ) -> FreshnessLevel:
        """Return the least trustworthy required-source freshness.

        UNKNOWN wins when a required source has no trustworthy timestamp.
        Otherwise STALE > RECENT > FRESH.
        """

        if not levels:
            return FreshnessLevel.UNKNOWN
        rank = {
            FreshnessLevel.FRESH: 0,
            FreshnessLevel.RECENT: 1,
            FreshnessLevel.STALE: 2,
            FreshnessLevel.UNKNOWN: 3,
        }
        return max(levels, key=rank.__getitem__)
