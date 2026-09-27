from mining_guardian.observability.models import Quality, Source
from mining_guardian.observability.pool import pool_observations
from tests.unit.test_runtime_miner import canonical


def test_pool_identity_raw_unknown_units_and_provenance():
    source = canonical({"algorithm": "pearlhash", "pool": {
        "pool": "stratum://user:secret@pool.invalid:3333", "latency": 0,
        "last_job_received": 21, "time_connected": "2026-01-01 00:00:00"}}).observations[0]
    records = pool_observations(source)
    fields = {r.signal: r for r in records}
    assert fields["endpoint"].value == "stratum://pool.invalid:3333"
    assert fields["latency"].value == 0
    assert fields["last_job_received"].value == 21
    assert fields["latency"].unit is None and fields["latency"].quality == Quality.UNKNOWN
    assert fields["uptime"].quality == Quality.MISSING
    assert all(r.source == Source.POOL_DATA_FROM_MINER and r.observation_time is None for r in records)
    assert all(r.correlation_id == source.correlation_id for r in records)
    assert all(r.provenance["payload_observation_id"] == str(source.observation_id) for r in records)
    assert "secret" not in "".join(r.model_dump_json() for r in records)


def test_missing_and_malformed_pool_do_not_assert_availability():
    missing = pool_observations(canonical({"algorithm": "unknown"}).observations[0])
    assert all(r.quality == Quality.MISSING and r.source_instance is None for r in missing)
    malformed = pool_observations(canonical({"algorithm": "unknown", "pool": [1]}).observations[0])
    assert malformed[0].quality == Quality.CORRUPTED
