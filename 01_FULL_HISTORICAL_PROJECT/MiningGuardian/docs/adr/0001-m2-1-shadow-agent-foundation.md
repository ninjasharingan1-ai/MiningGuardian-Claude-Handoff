# ADR 0001 — M2.1 Shadow Agent Foundation

## Problem

Mining Guardian needs a future reasoning layer without allowing model output to mutate the miner,
GPU, wallet, pool, or process state. The reasoning input must remain compact, algorithm-aware,
auditable, and reconstructable from persisted M0/M1 telemetry.

## Context and evidence

- M0/M1 already provides typed, read-only telemetry and SQLite persistence.
- Agent-context engineering benefits from compact high-signal context rather than passing unbounded
  raw history into a model.
- Agent memory research distinguishes episodic observations from higher-level reflections or durable
  lessons; Mining Guardian should not collapse those concepts.
- M2.1 explicitly forbids external model calls and all execution.

Relevant external sources considered:

- Park et al., *Generative Agents: Interactive Simulacra of Human Behavior* (2023).
- Shinn et al., *Reflexion: Language Agents with Verbal Reinforcement Learning* (2023).
- Anthropic, *Building effective agents* (2024).
- Anthropic, *Effective context engineering for AI agents* (2025).

## Candidates

1. Send raw telemetry rows directly to a future model.
2. Build a framework-heavy autonomous agent now.
3. Add deterministic telemetry summarization, typed memory, a provider-neutral gateway, and an
   append-only decision journal while keeping execution structurally absent.

## Decision

Choose option 3.

The deterministic core builds `MiningWorldState`, bounded time-window summaries, and
`AgentWorkingMemory`. A `ModelGateway` returns typed reasoning. `ShadowMiningAgent` validates and
persists that reasoning but has no dependency on miner/GPU adapters and no execution interface.

## Tradeoffs

- Storing the exact working-memory JSON in each decision duplicates a small amount of derived data,
  but preserves the exact cognitive input for auditability.
- `Base.metadata.create_all()` is sufficient for M2.1 because only new tables are added. Any future
  change to existing table columns should introduce an explicit migration mechanism.
- Simple first/last slopes and arithmetic means are intentionally used instead of advanced time
  series methods until evidence justifies additional complexity.

## Metrics and verification

- Existing M0/M1 tests remain green.
- M2.1 tests cover deterministic summaries, serialization, persistence, migration behavior, CLI,
  fake gateway behavior, and structural non-execution.
- Static source checks reject process/hardware/network-control dependencies in the agent package.

## Failure modes

- Sparse telemetry can make a window misleading; windows require at least two distinct timestamps.
- Missing data must remain explicit rather than becoming zero.
- Algorithm-specific samples must never be averaged together.
- Model reasoning must never overwrite measured or derived telemetry.

## Reconsideration triggers

Revisit this decision when M2.2 introduces a real model provider, when context size becomes a measured
bottleneck, or when evaluation evidence shows the current deterministic summaries omit necessary
signals.
