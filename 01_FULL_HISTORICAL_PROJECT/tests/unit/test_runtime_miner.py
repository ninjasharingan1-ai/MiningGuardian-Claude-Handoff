import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from mining_guardian.adapters.srbminer import SRBMinerClient, _integer, _number
from mining_guardian.observability.miner import MinerObserver, canonicalize_miner
from mining_guardian.observability.models import Quality
from mining_guardian.observability.payloads import MAX_STRING_LENGTH, safe_payload


def canonical(payload):
    return canonicalize_miner(payload, endpoint="http://localhost:21550/", ingestion_time=datetime.now(UTC),
                              correlation_id=uuid4(), guardian_session_id="g")


def test_real_fixture_provenance_and_multialgorithm_survival():
    payload = json.loads(Path("tests/fixtures/srbminer_3_6_4.json").read_text())
    payload["algorithms"].extend([42, {"shares": {}}, {"name": "NeverSeen", "hashrate_hs": 0}])
    result = canonical(payload)
    assert len(result.snapshot.workloads) == 2
    assert sum(r.quality == Quality.CORRUPTED for r in result.observations) == 2
    raw = result.observations[0].value
    assert raw["rig_name"] == "MiningGuardian"
    assert raw["gpu_devices"][0]["topology_id"] == "0000:01:00.0"
    rates = [r.value for r in result.observations if r.signal == "hashrate_hs"]
    assert rates == [32459610144862.57, 0]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), -1, 1.5, 2**64, "1e999"])
def test_invalid_counters_never_promoted(value):
    result = canonical({"algorithm": "pearlhash", "accepted": value})
    record = next(r for r in result.observations if r.signal == "accepted_shares")
    assert record.value is None
    assert record.quality in (Quality.CORRUPTED, Quality.OUT_OF_RANGE)
    assert _integer(value) is None
    assert _number(float("inf")) is None


def test_redaction_and_unknown_units():
    result = canonical({"algorithm": "pearlhash", "hashrate": 3, "unit": "mystery",
                        "api_key": "secret-value", "pool": "stratum://user:password@pool:3"})
    encoded = result.observations[0].model_dump_json()
    assert "secret-value" not in encoded and "user:password" not in encoded
    assert next(r for r in result.observations if r.signal == "hashrate_hs").value is None


@pytest.mark.parametrize("name", ["Unknown@Variant", "Unknown:Variant", "Unknown/Variant",
                                  "Unknown#Variant", "Unknown?Variant"])
def test_algorithm_identity_punctuation_survives_canonicalization(name):
    result = canonical({"algorithm": name, "hashrate_hs": 0})
    assert result.observations[0].value["algorithm"] == name
    assert result.snapshot.workloads[0].raw_algorithm_name == name
    hashrate = next(record for record in result.observations if record.signal == "hashrate_hs")
    assert hashrate.provenance["raw_algorithm_name"] == name


@pytest.mark.parametrize("name", ["alice@rig", "worker:01", "rig/a", "node#4", "worker?variant"])
def test_worker_and_rig_identity_punctuation_survives_raw_evidence(name):
    result = canonical({"algorithm": "pearlhash", "worker_name": name, "rig_name": name,
                        "gpu_devices": [{"device": name}]})
    raw = result.observations[0].value
    assert raw["worker_name"] == name
    assert raw["rig_name"] == name
    assert raw["gpu_devices"][0]["device"] == name


def test_nested_endpoint_and_secret_redaction_preserves_other_workload_identities():
    endpoint = "stratum+tcp://user:pass@pool.example.invalid:3333/path?token=query-secret#fragment"
    result = canonical({"rig_name": "rig@home", "workloads": [
        {"algorithm": "pearlhash", "pool": {"pool": endpoint, "worker": "alice@rig",
                                          "auth": "auth-secret", "password": "password-secret"},
         "api_key": "key-secret", "nested": {"access_token": "nested-secret"}},
        {"algorithm": "Unknown@Variant", "worker_name": "worker?variant",
         "pool": {"endpoint": endpoint, "passwd": "passwd-secret"}},
    ]})
    raw = result.observations[0].value
    assert raw["rig_name"] == "rig@home"
    assert raw["workloads"][0]["pool"]["worker"] == "alice@rig"
    assert raw["workloads"][1]["algorithm"] == "Unknown@Variant"
    assert raw["workloads"][1]["worker_name"] == "worker?variant"
    sanitized = "stratum+tcp://pool.example.invalid:3333/path"
    assert raw["workloads"][0]["pool"]["pool"] == sanitized
    assert raw["workloads"][1]["pool"]["endpoint"] == sanitized
    assert raw["workloads"][0]["api_key"] == "[REDACTED]"
    assert raw["workloads"][0]["nested"]["access_token"] == "[REDACTED]"
    assert raw["workloads"][0]["pool"]["auth"] == "[REDACTED]"
    assert raw["workloads"][0]["pool"]["password"] == "[REDACTED]"
    assert raw["workloads"][1]["pool"]["passwd"] == "[REDACTED]"
    encoded = result.observations[0].model_dump_json()
    assert all(secret not in encoded for secret in ("user:pass", "query-secret", "auth-secret",
                                                     "password-secret", "key-secret", "nested-secret",
                                                     "passwd-secret"))


def test_json_key_and_value_string_bounds():
    within = "x" * MAX_STRING_LENGTH
    over = within + "x"
    assert safe_payload({within: within}) == {within: within}
    assert safe_payload({"password": within}) == {"password": "[REDACTED]"}
    with pytest.raises(ValueError, match="payload_string_limit"):
        safe_payload({over: 0})
    with pytest.raises(ValueError, match="payload_string_limit"):
        safe_payload({"field": over})
    with pytest.raises(ValueError, match="payload_string_limit"):
        safe_payload({"password": over})
    with pytest.raises(ValueError, match="payload_string_limit"):
        safe_payload({"password": {"nested": over}})


def test_malformed_endpoint_value_redacts_without_rewriting_identity():
    assert safe_payload({"algorithm": "Unknown@Variant", "pool": "not a host:3333"}) == {
        "algorithm": "Unknown@Variant", "pool": "[REDACTED_ENDPOINT]"}


@pytest.mark.asyncio
@pytest.mark.parametrize("content,status", [(b'{"a":1,"a":2}', 200), (b'[]', 200), (b'x', 503), (b'x' * 1_048_577, 200)],
                         ids=["duplicate-key", "array", "unavailable", "oversized"])
async def test_hostile_http_payload_is_structured_failure(content, status):
    client = SRBMinerClient(transport=httpx.MockTransport(lambda request: httpx.Response(status, content=content)))
    result = await MinerObserver(client).collect(uuid4(), "g")
    assert result.snapshot is None
    assert result.observations[0].quality in (Quality.CORRUPTED, Quality.SOURCE_UNAVAILABLE)


@pytest.mark.asyncio
async def test_compressed_response_rejected_before_decompression():
    import gzip

    def handle(request):
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, headers={"content-encoding": "gzip"},
                              stream=httpx.ByteStream(gzip.compress(b"x" * 2_000_000)))

    result = await MinerObserver(SRBMinerClient(transport=httpx.MockTransport(handle))).collect(uuid4(), None)
    assert result.snapshot is None and result.observations[0].quality == Quality.CORRUPTED


@pytest.mark.asyncio
async def test_total_request_timeout_is_unavailable_not_health_or_corruption():
    import asyncio

    async def handle(request):
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={})

    result = await MinerObserver(SRBMinerClient(timeout=0.001, transport=httpx.MockTransport(handle))).collect(uuid4(), None)
    assert result.snapshot is None
    assert result.observations[0].quality == Quality.SOURCE_UNAVAILABLE


def test_conversion_overflow_and_malformed_nested_workloads():
    result = canonical({"workloads": {"Future": {"hashrate_mhs": 1e308, "shares": []}}})
    assert next(r for r in result.observations if r.signal == "hashrate_hs").quality == Quality.OUT_OF_RANGE
    assert next(r for r in result.observations if r.signal == "shares_parse").quality == Quality.CORRUPTED
    assert canonical({"workloads": 1}).observations[-1].quality == Quality.CORRUPTED
