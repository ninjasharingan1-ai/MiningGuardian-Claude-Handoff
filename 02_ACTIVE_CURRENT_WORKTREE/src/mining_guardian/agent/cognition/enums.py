from enum import StrEnum


class EvidenceType(StrEnum):
    MEASURED = "measured"
    DERIVED = "derived"
    HISTORICAL = "historical"
    EXTERNAL = "external"
    LESSON = "lesson"
    HYPOTHESIS = "hypothesis"


class Reliability(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class ClaimType(StrEnum):
    OBSERVATION = "observation"
    DERIVED_RESULT = "derived_result"
    CAUSAL_CLAIM = "causal_claim"
    PREDICTION = "prediction"


class ClaimStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class HypothesisStatus(StrEnum):
    ACTIVE = "active"
    SUPPORTED = "supported"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class NextStep(StrEnum):
    NO_ACTION = "no_action"
    OBSERVE_LONGER = "observe_longer"
    REQUEST_MORE_EVIDENCE = "request_more_evidence"
