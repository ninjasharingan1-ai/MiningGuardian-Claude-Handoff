"""Mining Guardian M0/M1 read-only telemetry foundation."""

__version__ = "0.1.0"

from .adapters import NVMLClient, SRBMinerClient
from .collectors import HardwareCollector, MinerCollector
from .config import Settings, get_database_url, get_settings
from .core import AlgorithmRegistry, SessionManager
from .formatting import format_hashrate

__all__ = [
    "AlgorithmRegistry",
    "HardwareCollector",
    "MinerCollector",
    "NVMLClient",
    "SRBMinerClient",
    "SessionManager",
    "Settings",
    "format_hashrate",
    "get_database_url",
    "get_settings",
]
