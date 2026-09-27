from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from mining_guardian.observability.models import Quality, RuntimeObservation, Source


def observation(**changes):
    data = {"source": Source.NVML, "source_instance": "GPU-tested", "signal": "throttle",
            "value": 0, "unit": "bitmask", "ingestion_time": datetime(2026, 1, 1, tzinfo=UTC),
            "correlation_id": uuid4(), "quality": Quality.VALID}
    data.update(changes)
    return RuntimeObservation(**data)


def test_identity_zero_missing_and_json_roundtrip():
    first, second = observation(), observation()
    assert first.observation_id != second.observation_id
    assert first.quality == Quality.VALID and first.value == 0
    assert observation(value=None).quality == Quality.MISSING
    assert first.observation_time is None and first.event_time is None
    assert RuntimeObservation.model_validate_json(first.model_dump_json()) == first
    assert observation(source_instance=None).quality == Quality.UNKNOWN


def test_precedence_preserves_secondary_evidence():
    record = observation(quality_conditions=(Quality.STALE, Quality.CORRUPTED, Quality.DELAYED))
    assert record.quality == Quality.CORRUPTED
    assert Quality.STALE in record.quality_conditions
    assert Quality.DELAYED in record.quality_conditions


@pytest.mark.parametrize("changes", [
    {"value": float("nan")}, {"value": float("inf")}, {"value": {"nested": float("inf")}},
    {"source": "LLM"}, {"schema_version": "future"}, {"correlation_id": "row-1"},
    {"ingestion_time": datetime(2026, 1, 1)}, {"unexpected": "input"},
])
def test_untrusted_contract_inputs_rejected(changes):
    with pytest.raises(ValidationError):
        observation(**changes)


def test_source_recording_and_receipt_are_distinct():
    recorded = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=3)))
    record = observation(observation_time=recorded)
    assert record.observation_time == datetime(2025, 12, 31, 21, tzinfo=UTC)
    assert record.ingestion_time == datetime(2026, 1, 1, tzinfo=UTC)
    assert record.event_time is None
