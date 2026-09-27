# ADR 0002 — M2.1.1 Temporal Semantics

## Status

Accepted for M2.1.1.

## Problem

Persisted telemetry was previously rendered as if it described the present. Observation origin,
sample age, Guardian session lifecycle, and miner API reachability are independent facts and must
not be collapsed into one status.

## Decision

Mining Guardian represents observation origin and freshness separately.

- `ObservationOrigin` identifies `LIVE_PROBE` or `PERSISTED`.
- `FreshnessPolicy` classifies sample age as `FRESH`, `RECENT`, `STALE`, or `UNKNOWN`.
- Defaults are 30 seconds for fresh and 120 seconds for recent; configuration owns the thresholds.
- Overall WorldState freshness is conservative across required miner and hardware sources:
  `UNKNOWN` is least trustworthy, followed by `STALE`, `RECENT`, and `FRESH`.
- Guardian session lifecycle is derived only from persisted Guardian session start/end facts.
  Miner reachability does not make a Guardian session active.
- Active sessions expose age. Ended sessions expose fixed duration and no active age.
- Persisted context windows classify freshness against wall-clock generation time, not against the
  session end time. An ended historical `5m` window can therefore be stale.
- One-shot live probing is ephemeral. It reads SRBMiner and NVML exactly once, performs
  non-discovering algorithm-registry resolution, and writes no mining session or telemetry rows.
- Legacy M2.1 journal JSON without new temporal fields remains readable using `UNKNOWN` / `None`.

## Consequences

Future model reasoning can use stale historical evidence without mistaking it for present-time
truth. No M2.2 capability, AI provider, control path, or hardware/miner mutation is introduced.
