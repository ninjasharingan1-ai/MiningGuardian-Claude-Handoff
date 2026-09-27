from datetime import UTC, datetime, timedelta

from mining_guardian.agent.context import ContextBuilder, WorldStateBuilder
from mining_guardian.agent.temporal import (
    FreshnessLevel,
    FreshnessPolicy,
    GuardianSessionStatus,
    ObservationOrigin,
)
from mining_guardian.core import AlgorithmRegistry
from mining_guardian.models import HardwareSample, MinerSample, SessionRecord
from mining_guardian.storage import (
    HardwareSampleRepository,
    MinerSampleRepository,
    SessionRepository,
)


def _seed(
    temp_db,
    *,
    session_id: str,
    started: datetime,
    ended: datetime | None,
    sample_times: list[datetime],
    include_version: bool = True,
) -> None:
    record = SessionRecord(
        session_id=session_id,
        miner="srbminer",
        gpu_ids=[0],
        algorithm_ids=["pearlpow"],
        raw_algorithm_names=["pearlhash"],
        start_time=started,
        end_time=ended,
    )
    with temp_db.get_session() as session:
        AlgorithmRegistry(session)
        SessionRepository(session).create(record)
        miner_repo = MinerSampleRepository(session)
        hardware_repo = HardwareSampleRepository(session)
        for index, timestamp in enumerate(sample_times):
            miner_repo.create(
                MinerSample(
                    timestamp=timestamp,
                    session_id=session_id,
                    miner="srbminer",
                    raw_algorithm_name="pearlhash",
                    canonical_algorithm_id="pearlpow",
                    canonical_algorithm_name="PearlPow",
                    local_hashrate_hs=32_000_000_000_000 + index,
                    accepted_shares=index,
                    rejected_shares=0,
                    device_ids=[1],
                    raw_data={"miner_version": "3.6.4"} if include_version else {},
                )
            )
            hardware_repo.create(
                HardwareSample(
                    timestamp=timestamp,
                    session_id=session_id,
                    gpu_id=0,
                    miner="srbminer",
                    algorithm_ids=["pearlpow"],
                    temperature_c=60 + index,
                    utilization_gpu=95,
                    power_w=35,
                )
            )


def test_freshness_policy_boundaries_and_unknown():
    policy = FreshnessPolicy(fresh_max_age_seconds=30, recent_max_age_seconds=120)
    assert policy.classify_age(None) is FreshnessLevel.UNKNOWN
    assert policy.classify_age(0) is FreshnessLevel.FRESH
    assert policy.classify_age(30) is FreshnessLevel.FRESH
    assert policy.classify_age(30.001) is FreshnessLevel.RECENT
    assert policy.classify_age(120) is FreshnessLevel.RECENT
    assert policy.classify_age(120.001) is FreshnessLevel.STALE


def test_freshness_policy_uses_timezone_aware_timestamps():
    policy = FreshnessPolicy()
    now = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    sample = datetime(2026, 9, 16, 9, 59, 45, tzinfo=UTC)
    assert policy.classify_timestamp(sample, now=now) is FreshnessLevel.FRESH
    assert policy.classify_timestamp(None, now=now) is FreshnessLevel.UNKNOWN


def test_overall_freshness_is_conservative():
    policy = FreshnessPolicy()
    assert (
        policy.conservative_overall(FreshnessLevel.FRESH, FreshnessLevel.STALE)
        is FreshnessLevel.STALE
    )
    assert (
        policy.conservative_overall(FreshnessLevel.FRESH, FreshnessLevel.UNKNOWN)
        is FreshnessLevel.UNKNOWN
    )


def test_active_session_reports_age_not_duration(temp_db):
    started = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)
    sample_times = [started, started + timedelta(seconds=10)]
    _seed(
        temp_db,
        session_id="active",
        started=started,
        ended=None,
        sample_times=sample_times,
    )
    with temp_db.get_session() as session:
        state = WorldStateBuilder(
            SessionRepository(session),
            MinerSampleRepository(session),
            HardwareSampleRepository(session),
        ).build("active", now=started + timedelta(seconds=20))
        assert state.observation_origin is ObservationOrigin.PERSISTED
        assert state.facts.guardian_session_status is GuardianSessionStatus.ACTIVE
        assert state.derived.session_age_seconds == 20
        assert state.derived.session_duration_seconds is None
        assert state.generated_at.tzinfo is not None
        assert state.latest_miner_sample_at is not None
        assert state.latest_miner_sample_at.tzinfo is not None


def test_ended_session_reports_duration_not_age(temp_db):
    started = datetime(2026, 9, 16, 8, 0, tzinfo=UTC)
    ended = started + timedelta(seconds=61)
    _seed(
        temp_db,
        session_id="ended",
        started=started,
        ended=ended,
        sample_times=[started, started + timedelta(seconds=60)],
    )
    with temp_db.get_session() as session:
        state = WorldStateBuilder(
            SessionRepository(session),
            MinerSampleRepository(session),
            HardwareSampleRepository(session),
        ).build("ended", now=ended + timedelta(hours=2))
        assert state.facts.guardian_session_status is GuardianSessionStatus.ENDED
        assert state.derived.session_age_seconds is None
        assert state.derived.session_duration_seconds == 61
        assert state.freshness is FreshnessLevel.STALE
        assert not state.context_validity.is_current_state_usable


def test_historical_window_is_stale_and_not_called_current_session(temp_db):
    started = datetime(2026, 9, 16, 7, 0, tzinfo=UTC)
    ended = started + timedelta(minutes=1)
    _seed(
        temp_db,
        session_id="historical",
        started=started,
        ended=ended,
        sample_times=[started, started + timedelta(seconds=60)],
    )
    with temp_db.get_session() as session:
        windows = ContextBuilder(
            SessionRepository(session),
            MinerSampleRepository(session),
            HardwareSampleRepository(session),
        ).build("historical", now=ended + timedelta(hours=1))
        assert windows
        assert all(window.observation_origin is ObservationOrigin.PERSISTED for window in windows)
        assert all(window.freshness is FreshnessLevel.STALE for window in windows)
        assert all(window.session_status is GuardianSessionStatus.ENDED for window in windows)
        assert "current_session" not in {window.label for window in windows}
        assert "last_session" in {window.label for window in windows}
        assert all(window.latest_sample_at.tzinfo is not None for window in windows)


def test_recent_window_uses_wall_clock_freshness(temp_db):
    started = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    samples = [started, started + timedelta(seconds=10)]
    _seed(
        temp_db,
        session_id="recent",
        started=started,
        ended=None,
        sample_times=samples,
    )
    with temp_db.get_session() as session:
        windows = ContextBuilder(
            SessionRepository(session),
            MinerSampleRepository(session),
            HardwareSampleRepository(session),
        ).build("recent", now=started + timedelta(seconds=20))
        five = next(window for window in windows if window.label == "5m")
        assert five.freshness is FreshnessLevel.FRESH
        assert five.session_status is GuardianSessionStatus.ACTIVE


def test_legacy_historical_sample_without_version_remains_valid(temp_db):
    started = datetime(2026, 9, 16, 6, 0, tzinfo=UTC)
    _seed(
        temp_db,
        session_id="legacy",
        started=started,
        ended=started + timedelta(seconds=10),
        sample_times=[started, started + timedelta(seconds=10)],
        include_version=False,
    )
    with temp_db.get_session() as session:
        state = WorldStateBuilder(
            SessionRepository(session),
            MinerSampleRepository(session),
            HardwareSampleRepository(session),
        ).build("legacy", now=started + timedelta(hours=1))
        assert state.facts.miner_version is None
        assert "miner_version" in state.missing_signals
