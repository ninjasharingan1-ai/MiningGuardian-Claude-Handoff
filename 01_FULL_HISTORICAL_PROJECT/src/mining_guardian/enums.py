from enum import StrEnum


class CapabilityState(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    NO_PERMISSION = "no_permission"
    UNKNOWN = "unknown"


class AlgorithmStatus(StrEnum):
    BUILT_IN = "built_in"
    DISCOVERED = "discovered"
    VERIFIED = "verified"
    UNKNOWN = "unknown"
    DEPRECATED = "deprecated"


class SessionState(StrEnum):
    BOOT = "boot"
    OBSERVE = "observe"


class SessionHealth(StrEnum):
    HEALTHY = "healthy"
    WARNING = "warning"
    DEGRADED = "degraded"
    FAILED = "failed"


class EventType(StrEnum):
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"
    ALGORITHM_DISCOVERED = "algorithm_discovered"
    MINER_API_ERROR = "miner_api_error"
    NVML_ERROR = "nvml_error"


class EventSeverity(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ExperimentResult(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    ROLLBACK = "rollback"
    INCONCLUSIVE = "inconclusive"


class OptimizationMode(StrEnum):
    REWARD_FIRST = "reward_first"
    EFFICIENCY_FIRST = "efficiency_first"
    BALANCED = "balanced"
