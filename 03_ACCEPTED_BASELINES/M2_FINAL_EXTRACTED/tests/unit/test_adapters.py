import pytest

from mining_guardian.models import MinerWorkload
from tests.fixtures.fakes import FakeNVMLClient, FakeSRBMinerClient


@pytest.mark.asyncio
async def test_fake_miner_one_workload():
    miner = FakeSRBMinerClient()
    snapshot = await miner.snapshot()
    assert snapshot is not None
    assert len(snapshot.workloads) == 1


@pytest.mark.asyncio
async def test_fake_miner_multiple_workloads():
    miner = FakeSRBMinerClient(
        workloads=[
            MinerWorkload(raw_algorithm_name="pearlhash", hashrate_hs=1),
            MinerWorkload(raw_algorithm_name="FutureHash", hashrate_hs=2),
        ]
    )
    snapshot = await miner.snapshot()
    assert snapshot is not None
    assert len(snapshot.workloads) == 2


@pytest.mark.asyncio
async def test_fake_miner_unknown_and_missing_data():
    miner = FakeSRBMinerClient(
        workloads=[MinerWorkload(raw_algorithm_name="NeverSeenBefore", hashrate_hs=None)]
    )
    snapshot = await miner.snapshot()
    assert snapshot is not None
    assert snapshot.workloads[0].hashrate_hs is None


@pytest.mark.asyncio
async def test_fake_miner_unavailable_returns_none_not_zero():
    miner = FakeSRBMinerClient(alive=False)
    assert await miner.snapshot() is None
    assert await miner.local_hashrate_hs() is None


@pytest.mark.asyncio
async def test_fake_miner_has_no_method_attribute_collisions():
    miner = FakeSRBMinerClient()
    assert callable(miner.accepted_shares)
    assert callable(miner.rejected_shares)
    assert callable(miner.local_hashrate_hs)


def test_fake_nvml_read_only_surface():
    nvml = FakeNVMLClient()
    assert nvml.get_gpu_info(0) is not None
    assert not hasattr(nvml, "set_power_limit")
    assert not hasattr(nvml, "set_core_offset")
    assert not hasattr(nvml, "set_fan")
