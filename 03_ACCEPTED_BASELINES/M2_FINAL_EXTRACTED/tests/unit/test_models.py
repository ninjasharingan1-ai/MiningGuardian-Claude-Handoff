from datetime import datetime

from mining_guardian.enums import AlgorithmStatus, CapabilityState
from mining_guardian.models import (
    AlgorithmRecord,
    HardwareSample,
    MinerWorkload,
    ProfileScope,
    SessionRecord,
)


def test_capability_states():
    assert CapabilityState.SUPPORTED.value == "supported"
    assert CapabilityState.UNSUPPORTED.value == "unsupported"
    assert CapabilityState.NO_PERMISSION.value == "no_permission"
    assert CapabilityState.UNKNOWN.value == "unknown"


def test_algorithm_record():
    record = AlgorithmRecord(
        algorithm_id="pearlpow",
        canonical_name="PearlPow",
        display_name="PearlPow",
        status=AlgorithmStatus.VERIFIED,
        source="built_in",
        optimizer_eligible=True,
    )
    assert record.canonical_name == "PearlPow"


def test_workload_preserves_raw_name_and_unknown_values():
    workload = MinerWorkload(raw_algorithm_name="FutureHash-X9")
    assert workload.raw_algorithm_name == "FutureHash-X9"
    assert workload.hashrate_hs is None
    assert workload.accepted_shares is None


def test_hardware_sample_can_correlate_algorithms():
    sample = HardwareSample(
        timestamp=datetime.now(),
        session_id="s1",
        gpu_id=0,
        miner="srbminer",
        algorithm_ids=["pearlpow", "future"],
    )
    assert sample.algorithm_ids == ["pearlpow", "future"]


def test_payout_coin_is_separate_from_algorithm():
    record = SessionRecord(
        session_id="s1",
        miner="srbminer",
        gpu_ids=[0],
        algorithm_ids=["pearlpow"],
        payout_coin="DOGE",
        start_time=datetime.now(),
    )
    assert record.algorithm_ids == ["pearlpow"]
    assert record.payout_coin == "DOGE"


def test_future_profile_scope_is_algorithm_and_miner_specific():
    pearl = ProfileScope(gpu_id=0, algorithm_id="pearlpow", miner="srbminer", profile_name="baseline")
    other = ProfileScope(gpu_id=0, algorithm_id="other", miner="srbminer", profile_name="baseline")
    assert pearl != other
