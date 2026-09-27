from datetime import timedelta

import pytest
from pydantic import ValidationError

from mining_guardian.observability.models import Quality, Source
from mining_guardian.observability.temporal import FreshnessRule, elapsed, evaluate_freshness
from tests.unit.test_runtime_observation import observation


def test_configured_boundary_delay_and_missing_source_time():
    base = observation()
    rule = FreshnessRule(source=Source.NVML, signal="throttle", stale_after_seconds=10,
                         delayed_after_seconds=2)
    assert evaluate_freshness(base, base.ingestion_time, (rule,)).freshness.state == "UNKNOWN"
    source = observation(observation_time=base.ingestion_time,
                         event_time=base.ingestion_time - timedelta(seconds=3))
    at_boundary = evaluate_freshness(source, base.ingestion_time + timedelta(seconds=10), (rule,))
    assert at_boundary.freshness.state == "CURRENT"
    assert at_boundary.quality == Quality.DELAYED
    stale = evaluate_freshness(source, base.ingestion_time + timedelta(seconds=11), (rule,))
    assert Quality.STALE in stale.quality_conditions
    assert stale.quality == Quality.DELAYED
    assert source.quality == Quality.VALID  # evaluation does not rewrite stored evidence


def test_clock_manipulation_and_unconfigured_signal():
    base = observation()
    assert evaluate_freshness(base, base.ingestion_time - timedelta(seconds=1)).quality == Quality.OUT_OF_RANGE
    assert evaluate_freshness(base, base.ingestion_time).freshness.state == "UNKNOWN"
    assert elapsed(5, lambda: 7) == 2
    with pytest.raises(ValueError):
        elapsed(5, lambda: 4)
    with pytest.raises(ValueError):
        evaluate_freshness(base, base.ingestion_time.replace(tzinfo=None))


@pytest.mark.parametrize("value", [-1, float("inf"), float("nan")])
def test_invalid_freshness_configuration(value):
    with pytest.raises(ValidationError):
        FreshnessRule(source=Source.NVML, signal="throttle", stale_after_seconds=value)


def test_no_event_time_means_delay_unavailable_even_with_recording_time():
    base = observation()
    source = observation(observation_time=base.ingestion_time - timedelta(seconds=100))
    rule = FreshnessRule(source=Source.NVML, signal="throttle", stale_after_seconds=10,
                         delayed_after_seconds=2)
    result = evaluate_freshness(source, base.ingestion_time, (rule,))
    assert result.quality == Quality.STALE
    assert result.freshness.delay_seconds is None
