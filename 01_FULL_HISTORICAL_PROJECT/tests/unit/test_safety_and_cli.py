from pathlib import Path

from mining_guardian.cli.commands import cli
from mining_guardian.formatting import format_hashrate


def test_required_cli_commands_exist():
    assert {"probe-gpu", "probe-miner", "observe", "status", "agent-context", "agent-shadow-once"} <= set(cli.commands)


def test_status_formatter_is_not_mhs_hardcoded():
    assert format_hashrate(2_000) == "2.00 kH/s"
    assert format_hashrate(2_000_000_000_000) == "2.00 TH/s"


def test_no_generic_cross_algorithm_ranking_api():
    import mining_guardian
    assert not hasattr(mining_guardian, "rank_algorithms")
    assert not hasattr(mining_guardian, "compare_algorithm_hashrates")


def test_m1_source_has_no_control_or_shell_execution_paths():
    source_root = Path(__file__).resolve().parents[2] / "src" / "mining_guardian"
    forbidden_code_tokens = (
        "subprocess.",
        "os.system(",
        "pynvml.nvmlDeviceSet",
        ".restart(",
        ".kill(",
        ".terminate(",
        "switch_algorithm",
        "set_power_limit",
        "set_core_offset",
        "set_memory_offset",
        "set_fan",
    )
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in source_root.rglob("*.py")
    )
    for token in forbidden_code_tokens:
        assert token not in combined
