from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine

from mining_guardian.adapters.srbminer import SRBMinerClient
from mining_guardian.observability.compatibility import legacy_hardware
from mining_guardian.observability.miner import MinerObserver
from mining_guardian.observability.models import Quality, Source
from mining_guardian.observability.nvml import NVMLObserver
from mining_guardian.observability.observer import RuntimeObserver
from mining_guardian.storage.runtime_repository import RuntimeEvidenceRepository
from tests.unit.test_runtime_nvml import Binding


class FlakySink:
    def __init__(self, repository):
        self.repository = repository
        self.fail = True

    def save_cycle(self, records):
        if self.fail:
            raise RuntimeError("secret-password-not-for-logs")
        self.repository.save_cycle(records)


@pytest.mark.asyncio
@pytest.mark.parametrize("miner_ok,gpu_ok", [(False, True), (True, False), (False, False), (True, True)])
async def test_independent_sources_storage_recovery_and_single_request(miner_ok, gpu_ok, capsys):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200 if miner_ok else 503, json={"algorithm": "pearlhash", "hashrate_hs": 0})

    engine = create_engine("sqlite://")
    try:
        repository = RuntimeEvidenceRepository(engine)
        sink = FlakySink(repository)
        observer = RuntimeObserver(MinerObserver(SRBMinerClient(transport=httpx.MockTransport(handle))),
            NVMLObserver(Binding(), lambda: gpu_ok), sink)
        failed = await observer.collect_cycle("guardian")
        assert not failed.stored
        assert any(r.signal == "storage_failure" for r in failed.observations)
        assert any(r.source == Source.NVML and r.value == 0 for r in failed.observations) == gpu_ok
        assert any(r.signal == "hashrate_hs" and r.value == 0 for r in failed.observations) == miner_ok
        assert "secret-password-not-for-logs" not in capsys.readouterr().out
        sink.fail = False
        recovered = await observer.collect_cycle("guardian")
        assert recovered.stored
        assert repository.load_cycle(recovered.context.correlation_id) == recovered.observations
        assert any(r.signal == "previous_storage_failure" for r in recovered.observations)
        assert len(requests) == 2  # Exactly one HTTP request per cycle, no health/stats refetch.
        assert all(r.guardian_session_id == "guardian" for r in recovered.observations)
        assert all(value >= 0 for value in recovered.durations.values())
        projected = legacy_hardware(recovered.observations, gpu_index=0, session_id="guardian", algorithm_ids=[])
        if gpu_ok:
            assert projected.throttle_reasons == "0"
            assert projected.temperature_c is None
        else:
            assert projected is None
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_adapter_exception_is_structural_and_other_source_survives():
    class BrokenMiner:
        async def collect(self, *args):
            raise RuntimeError("malformed_adapter")

    class Sink:
        def save_cycle(self, records):
            self.records = records

    result = await RuntimeObserver(BrokenMiner(), NVMLObserver(Binding(), lambda: True), Sink()).collect_cycle(None)
    assert result.stored
    assert any(r.source == Source.SRBMINER_HTTP and r.quality == Quality.SOURCE_UNAVAILABLE for r in result.observations)
    assert any(r.source == Source.NVML and r.quality == Quality.VALID for r in result.observations)
    assert result.context.correlation_id != uuid4()


def test_cli_observe_wires_canonical_and_legacy_without_extra_reads(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from sqlalchemy import text

    from mining_guardian.cli import commands
    from mining_guardian.config import Settings
    from tests.fixtures.fakes import FakeNVMLClient

    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"algorithm": "NeverSeen", "hashrate_hs": 12})

    path = tmp_path / "observer.db"
    settings = Settings(_env_file=None, database_path=str(path), observe_interval_seconds=0.001)
    client = SRBMinerClient(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(commands, "get_settings", lambda: settings)
    monkeypatch.setattr(commands, "SRBMinerClient", lambda **kwargs: client)
    monkeypatch.setattr(commands, "NVMLClient", FakeNVMLClient)
    monkeypatch.setattr(commands, "pynvml", Binding())
    result = CliRunner().invoke(commands.cli, ["observe", "--duration", "0.01"])
    assert result.exit_code == 0, result.output
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    try:
        with engine.connect() as connection:
            cycles = connection.scalar(text("SELECT count(*) FROM m3_runtime_cycles_v1"))
            assert cycles == len(requests) and cycles > 0
            assert connection.scalar(text("SELECT count(*) FROM miner_samples")) == cycles
            assert connection.scalar(text("SELECT count(*) FROM hardware_samples")) == cycles
            assert connection.scalar(text("SELECT optimizer_eligible FROM algorithms WHERE canonical_name = 'NeverSeen'")) == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("name", ["Unknown@Variant", "Unknown:Variant", "Unknown/Variant",
                                  "Unknown#Variant", "Unknown?Variant"])
def test_canonical_unknown_name_reaches_registry_unchanged(temp_db, name):
    from mining_guardian.collectors.miner import MinerCollector
    from mining_guardian.core.algorithm_registry import AlgorithmRegistry
    from mining_guardian.observability.miner import canonicalize_miner

    acquisition = canonicalize_miner({"algorithm": name, "hashrate_hs": 0},
        endpoint="http://localhost:21550/", ingestion_time=datetime.now(UTC),
        correlation_id=uuid4(), guardian_session_id="guardian")
    with temp_db.get_session() as session:
        registry = AlgorithmRegistry(session)
        collector = MinerCollector(None, registry)
        with patch.object(registry, "resolve", wraps=registry.resolve) as resolve:
            samples = collector.project_snapshot(acquisition.snapshot, "guardian")
        assert resolve.call_args.args[0] == name
        assert len(samples) == 1
        assert samples[0].raw_algorithm_name == name
        assert samples[0].canonical_algorithm_name == name
        assert registry.repository.get(samples[0].canonical_algorithm_id).optimizer_eligible is False
