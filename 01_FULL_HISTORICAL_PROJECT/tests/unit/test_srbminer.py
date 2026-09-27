import json
from pathlib import Path
from typing import Any

import click.testing
import httpx
import pytest

from mining_guardian.adapters.srbminer import SRBMinerClient, parse_srbminer_payload
from mining_guardian.cli import commands
from mining_guardian.config import Settings
from mining_guardian.core import AlgorithmRegistry
from mining_guardian.formatting import format_hashrate


def _load_srbminer_3_6_4_fixture() -> dict[str, Any]:
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "srbminer_3_6_4.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_single_algorithm_explicit_hs():
    snapshot = parse_srbminer_payload(
        {
            "Algorithm": "pearlhash",
            "hashrate_hs": 27_400_000,
            "Shares": {"Accepted": 10, "Rejected": 2},
            "Uptime": 100,
        }
    )
    assert len(snapshot.workloads) == 1
    workload = snapshot.workloads[0]
    assert workload.raw_algorithm_name == "pearlhash"
    assert workload.hashrate_hs == 27_400_000
    assert workload.accepted_shares == 10
    assert snapshot.uptime_seconds == 100


def test_bare_hashrate_without_unit_is_unavailable_not_zero():
    snapshot = parse_srbminer_payload({"Algorithm": "pearlhash", "HashRate": 27.4})
    assert snapshot.workloads[0].hashrate_hs is None


def test_hashrate_unit_normalization_at_adapter_boundary():
    snapshot = parse_srbminer_payload(
        {"Algorithm": "pearlhash", "HashRate": 27.4, "HashRateUnit": "MH/s"}
    )
    assert snapshot.workloads[0].hashrate_hs == 27_400_000


def test_hashrate_string_normalization():
    snapshot = parse_srbminer_payload({"Algorithm": "pearlhash", "HashRate": "1.25 TH/s"})
    assert snapshot.workloads[0].hashrate_hs == 1_250_000_000_000


def test_multiple_algorithms():
    snapshot = parse_srbminer_payload(
        {
            "workloads": [
                {"algorithm": "pearlhash", "hashrate_hs": 10, "device_ids": [0]},
                {"algorithm": "FutureHash", "hashrate_hs": 20, "device_ids": [1]},
            ]
        }
    )
    assert [workload.raw_algorithm_name for workload in snapshot.workloads] == [
        "pearlhash",
        "FutureHash",
    ]
    assert snapshot.workloads[1].device_ids == [1]


def test_srbminer_algorithms_array_preserves_multiple_workloads():
    snapshot = parse_srbminer_payload(
        {
            "algorithms": [
                {"name": "pearlhash", "hashrate": {"1min": 10.0}},
                {"name": "FutureHash", "hashrate": {"1min": 20.0}},
            ]
        }
    )

    assert [workload.raw_algorithm_name for workload in snapshot.workloads] == [
        "pearlhash",
        "FutureHash",
    ]
    assert [workload.hashrate_hs for workload in snapshot.workloads] == [10.0, 20.0]


def test_srbminer_algorithms_array_missing_optional_fields_is_safe():
    snapshot = parse_srbminer_payload({"algorithms": [{"name": "pearlhash"}]})

    assert len(snapshot.workloads) == 1
    workload = snapshot.workloads[0]
    assert workload.hashrate_hs is None
    assert workload.total_shares is None
    assert workload.accepted_shares is None
    assert workload.rejected_shares is None
    assert workload.invalid_shares is None
    assert workload.gpu_compute_errors == {}


def test_schema_variation_dictionary_algorithms():
    snapshot = parse_srbminer_payload(
        {
            "Algorithms": {
                "pearlhash": {"hashrate_mhs": 2.5, "AcceptedShares": 3},
                "OtherAlgo": {"hashrate_khs": 8},
            }
        }
    )
    assert len(snapshot.workloads) == 2
    assert snapshot.workloads[0].hashrate_hs == 2_500_000
    assert snapshot.workloads[1].hashrate_hs == 8_000


def test_missing_fields_remain_unavailable():
    snapshot = parse_srbminer_payload({"Algorithm": "pearlhash"})
    workload = snapshot.workloads[0]
    assert workload.hashrate_hs is None
    assert workload.accepted_shares is None
    assert workload.rejected_shares is None
    assert workload.invalid_shares is None
    assert workload.gpu_hashrate_total_hs is None
    assert workload.gpu_compute_errors == {}


def test_verified_srbminer_3_6_4_payload_parses():
    snapshot = parse_srbminer_payload(_load_srbminer_3_6_4_fixture())

    assert snapshot.miner_version == "3.6.4"
    assert snapshot.uptime_seconds == 283
    assert len(snapshot.workloads) == 1

    workload = snapshot.workloads[0]
    assert workload.raw_algorithm_name == "pearlhash"
    assert workload.hashrate_hs == 32459610144862.57
    assert workload.hashrate_windows_hs == {
        "1min": 32459610144862.57,
        "1hr": 32394760917062.8,
        "6hr": 0.0,
        "12hr": 0.0,
    }
    assert workload.gpu_hashrate_total_hs == 32504670777591.94
    assert workload.gpu_hashrates_hs == {"gpu1": 32504670777591.94}
    assert workload.total_shares == 0
    assert workload.accepted_shares == 0
    assert workload.rejected_shares == 0
    assert workload.invalid_shares is None
    assert workload.gpu_compute_errors == {"gpu1": 0}
    assert workload.gpu_efficiency_raw == {"gpu1": 928704879359.77}
    assert workload.miner_device_names == ["gpu1"]
    assert workload.device_ids == []

    assert len(snapshot.devices) == 1
    device = snapshot.devices[0]
    assert device.miner_device_id == 1
    assert device.device_name == "gpu1"
    assert device.bus_id == 1
    assert device.topology_id == "0000:01:00.0"


def test_verified_srbminer_3_6_4_hashrate_formats_as_ths():
    snapshot = parse_srbminer_payload(_load_srbminer_3_6_4_fixture())
    assert format_hashrate(snapshot.workloads[0].hashrate_hs) == "32.46 TH/s"


def test_verified_pearlhash_resolves_through_registry(temp_db):
    snapshot = parse_srbminer_payload(_load_srbminer_3_6_4_fixture())
    with temp_db.get_session() as session:
        registry = AlgorithmRegistry(session)
        record, created = registry.resolve(
            snapshot.workloads[0].raw_algorithm_name,
            scope_type="miner",
            scope_name=snapshot.miner,
        )

    assert created is False
    assert record is not None
    assert record.algorithm_id == "pearlpow"
    assert record.canonical_name == "PearlPow"


@pytest.mark.asyncio
async def test_api_unavailable_is_safe():
    async def handler(_request):
        raise httpx.ConnectError("offline")

    client = SRBMinerClient(transport=httpx.MockTransport(handler))
    assert await client.snapshot() is None
    health = await client.health()
    assert health.is_alive is False


@pytest.mark.asyncio
async def test_malformed_json_is_safe():
    def handler(_request):
        return httpx.Response(200, content=b"{not-json", headers={"content-type": "application/json"})

    client = SRBMinerClient(transport=httpx.MockTransport(handler))
    assert await client.snapshot() is None


@pytest.mark.asyncio
async def test_configured_path_is_used():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        return httpx.Response(200, json={"Algorithm": "pearlhash", "hashrate_hs": 1})

    client = SRBMinerClient(api_path="/custom/read-only", transport=httpx.MockTransport(handler))
    snapshot = await client.snapshot()
    assert snapshot is not None
    assert seen["path"] == "/custom/read-only"


@pytest.mark.asyncio
async def test_non_object_json_is_safe():
    def handler(_request):
        return httpx.Response(200, json=[1, 2, 3])

    client = SRBMinerClient(transport=httpx.MockTransport(handler))
    assert await client.snapshot() is None


@pytest.mark.asyncio
async def test_local_srbminer_client_disables_proxy_environment(monkeypatch):
    captured_kwargs: dict[str, Any] = {}

    class RecordingAsyncClient:
        def __init__(self, **kwargs: Any):
            captured_kwargs.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _traceback):
            return None

        async def get(self, _url: str) -> httpx.Response:
            return httpx.Response(200, json={"Algorithm": "pearlhash", "hashrate_hs": 1})

    monkeypatch.setattr(httpx, "AsyncClient", RecordingAsyncClient)
    snapshot = await SRBMinerClient().snapshot()

    assert snapshot is not None
    assert captured_kwargs["trust_env"] is False


def test_probe_miner_reports_verified_srbminer_payload(monkeypatch, tmp_path):
    parsed_snapshot = parse_srbminer_payload(_load_srbminer_3_6_4_fixture())

    class FixtureSRBMinerClient:
        def __init__(self, **_kwargs: Any):
            pass

        async def snapshot(self):
            return parsed_snapshot.model_copy(deep=True)

    settings = Settings(database_path=str(tmp_path / "probe.db"))
    monkeypatch.setattr(commands, "get_settings", lambda: settings)
    monkeypatch.setattr(commands, "SRBMinerClient", FixtureSRBMinerClient)

    result = click.testing.CliRunner().invoke(commands.cli, ["probe-miner"])

    assert result.exit_code == 0, result.output
    assert "Miner: srbminer" in result.output
    assert "Version: 3.6.4" in result.output
    assert "Uptime: 283 seconds" in result.output
    assert "Raw Algorithm: pearlhash" in result.output
    assert "Algorithm: PearlPow" in result.output
    assert "Hashrate: 32.46 TH/s" in result.output
    assert "Accepted: 0" in result.output
    assert "Rejected: 0" in result.output
