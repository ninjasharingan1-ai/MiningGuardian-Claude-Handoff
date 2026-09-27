from mining_guardian.observability.continuity import (
    AcquisitionContext,
    ContinuityEvidence,
    ContinuityTracker,
)
from mining_guardian.observability.models import Quality
from tests.unit.test_runtime_observation import observation


def test_acquisition_is_context_only_and_equal_values_not_duplicates():
    first, second = AcquisitionContext("guardian"), AcquisitionContext("guardian")
    assert first.correlation_id != second.correlation_id
    tracker = ContinuityTracker()
    evidence = ContinuityEvidence("gpu")
    assert tracker.assess(observation(), evidence).quality == Quality.VALID
    assert tracker.assess(observation(), evidence).quality == Quality.VALID


def test_duplicate_order_and_counter_discontinuity_preserve_reasons():
    tracker = ContinuityTracker()
    tracker.assess(observation(value=100), ContinuityEvidence("counter", True, "event-a", 10))
    repeat = tracker.assess(observation(value=100), ContinuityEvidence("counter", True, "event-a", 10))
    assert repeat.quality == Quality.DUPLICATED
    drop = tracker.assess(observation(value=1), ContinuityEvidence("counter", True, "event-b", 9))
    assert drop.quality == Quality.RESET_OR_DISCONTINUOUS
    assert Quality.OUT_OF_ORDER in drop.quality_conditions
    assert drop.quality_metadata["process_incarnation"] is None
    assert "cumulative_value_decreased_not_proof_of_restart" in drop.quality_metadata["continuity_reasons"]


def test_namespaces_incarnations_and_bounded_history():
    tracker = ContinuityTracker(max_streams=2)
    tracker.assess(observation(value=100), ContinuityEvidence("uptime", True, incarnation="a"))
    changed = tracker.assess(observation(value=101), ContinuityEvidence("uptime", True, incarnation="b"))
    assert changed.quality == Quality.RESET_OR_DISCONTINUOUS
    other = tracker.assess(observation(value=0, source_instance="other-gpu"), ContinuityEvidence("uptime", True))
    assert other.quality == Quality.VALID
    for index in range(10):
        tracker.assess(observation(source_instance=str(index)), ContinuityEvidence("gpu"))
    assert tracker.retained_streams == 2
