"""Bounded continuity diagnostics using explicit source evidence, never row order."""

from collections import OrderedDict, deque
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from .models import Quality, RuntimeObservation, with_conditions


@dataclass(frozen=True)
class AcquisitionContext:
    guardian_session_id: str | None
    correlation_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class ContinuityEvidence:
    """Caller must establish these identities from the source contract, not guesses."""

    stream_scope: str
    cumulative: bool = False
    stable_event_id: str | None = None
    sequence: int | None = None
    incarnation: str | None = None


@dataclass
class _Stream:
    previous: RuntimeObservation
    evidence: ContinuityEvidence
    events: deque[str] = field(default_factory=lambda: deque(maxlen=64))


class ContinuityTracker:
    def __init__(self, max_streams: int = 1024):
        if max_streams < 1:
            raise ValueError("max_streams must be positive")
        self.max_streams = max_streams
        self._streams: OrderedDict[tuple[str, str, str, str], _Stream] = OrderedDict()

    @property
    def retained_streams(self) -> int:
        return len(self._streams)

    def assess(self, record: RuntimeObservation, evidence: ContinuityEvidence) -> RuntimeObservation:
        if record.source_instance is None or not evidence.stream_scope:
            return with_conditions(record, quality_metadata={**record.quality_metadata,
                                   "continuity": "source_or_stream_identity_unavailable"})
        key = (record.source.value, record.source_instance, evidence.stream_scope, record.signal)
        previous = self._streams.get(key)
        conditions: list[Quality] = []
        reasons: list[str] = []
        if previous is not None:
            changed = (evidence.incarnation is not None and previous.evidence.incarnation is not None
                       and evidence.incarnation != previous.evidence.incarnation)
            if changed:
                conditions.append(Quality.RESET_OR_DISCONTINUOUS)
                reasons.append("explicit_source_incarnation_changed")
                previous.events.clear()
            else:
                if evidence.stable_event_id is not None and evidence.stable_event_id in previous.events:
                    conditions.append(Quality.DUPLICATED)
                    reasons.append("stable_source_event_identity_repeated")
                if evidence.sequence is not None and previous.evidence.sequence is not None and evidence.sequence < previous.evidence.sequence:
                    conditions.append(Quality.OUT_OF_ORDER)
                    reasons.append("source_sequence_regressed")
                if record.event_time is not None and previous.previous.event_time is not None and record.event_time < previous.previous.event_time:
                    conditions.append(Quality.OUT_OF_ORDER)
                    reasons.append("source_event_clock_regressed")
                current, old = record.value, previous.previous.value
                if evidence.cumulative and isinstance(current, (int, float)) and not isinstance(current, bool) and isinstance(old, (int, float)) and not isinstance(old, bool) and current < old:
                    conditions.append(Quality.RESET_OR_DISCONTINUOUS)
                    reasons.append("cumulative_value_decreased_not_proof_of_restart")
        if record.quality == Quality.VALID and Quality.OUT_OF_ORDER not in conditions and Quality.DUPLICATED not in conditions:
            stream = _Stream(record, evidence, previous.events if previous else deque(maxlen=64))
            if evidence.stable_event_id is not None:
                stream.events.append(evidence.stable_event_id)
            self._streams[key] = stream
            self._streams.move_to_end(key)
            if len(self._streams) > self.max_streams:
                self._streams.popitem(last=False)
        return with_conditions(record, *conditions, quality_metadata={**record.quality_metadata,
            "continuity_reasons": reasons,
            "duplicate_detection": "available" if evidence.stable_event_id is not None else "unavailable",
            "process_incarnation": evidence.incarnation,
            "history_scope": "bounded_in_process_only"})
