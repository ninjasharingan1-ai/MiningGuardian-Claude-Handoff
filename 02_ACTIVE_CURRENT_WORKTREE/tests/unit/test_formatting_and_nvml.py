from mining_guardian.adapters.nvml import _capability_from_exception
from mining_guardian.enums import CapabilityState
from mining_guardian.formatting import format_hashrate


class NvmlNoPermissionError(Exception):
    pass


class NvmlNotSupportedError(Exception):
    pass


class NvmlUnknownError(Exception):
    pass


def test_hashrate_formatter_units():
    assert format_hashrate(999) == "999.00 H/s"
    assert format_hashrate(1_500) == "1.50 kH/s"
    assert format_hashrate(2_500_000) == "2.50 MH/s"
    assert format_hashrate(3_000_000_000) == "3.00 GH/s"
    assert format_hashrate(4_000_000_000_000) == "4.00 TH/s"
    assert format_hashrate(5_000_000_000_000_000) == "5.00 PH/s"


def test_hashrate_formatter_unavailable():
    assert format_hashrate(None) == "unavailable"


def test_nvml_capability_permission():
    assert _capability_from_exception(NvmlNoPermissionError()) == CapabilityState.NO_PERMISSION


def test_nvml_capability_unsupported():
    assert _capability_from_exception(NvmlNotSupportedError("Not supported")) == CapabilityState.UNSUPPORTED


def test_nvml_capability_unknown():
    assert _capability_from_exception(NvmlUnknownError("driver error")) == CapabilityState.UNKNOWN
