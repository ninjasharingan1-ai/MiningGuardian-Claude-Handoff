# MiningGuardian — Claude Repository Entry Point

This repository is a forensic handoff and continuation surface for MiningGuardian.

## Canonical optimization objective

MAXIMIZE REALIZED MINING REWARD PER REAL-TIME EVALUATION BLOCK

subject to:

- hard GPU safety constraints;
- mining continuity;
- operational stability;
- evidence sufficiency;
- capability constraints.

Raw hashrate, TH/W, GPU clocks, temperature, power, latency,
stale rate, reject rate and similar metrics are NOT the final
optimization objective.

They are evidence, state variables, explanatory variables,
constraints, or intermediate optimization signals.

## Critical rule

Do NOT immediately begin implementation.

First perform a READ-ONLY forensic reconstruction.

The repository intentionally contains:

1. historical project material;
2. the active current worktree;
3. extracted accepted baselines;
4. forensic Git/history reports;
5. current checkpoint evidence.

These surfaces must NOT be merged automatically.

## Current accepted continuation checkpoint

Expected historical active checkpoint:

97b9837068f553085cc066a4134d165cb1a9c40c

Current completed implementation slice:

M3.2 S4A-R4

Current next implementation target:

M3.2 S4A-R5 — Missing-fraction fail-closed boundary

## Required reading order

Start with:

1. 05_INSTRUCTIONS/
2. 04_FORENSICS/CURRENT_ACCEPTED_CHECKPOINT.txt
3. accepted M2 authority/baseline material
4. accepted M3.1 freeze material
5. M3.2 architecture and implementation handoff
6. 02_ACTIVE_CURRENT_WORKTREE/

Then reconstruct historical-to-current supersession before editing.

## Important

The original packaged handoff ZIP had SHA-256:

A83689C162EEA529E7552DAC04918CDD554C769349CB610357AFBB88CBDFE56F

Binary ZIP and Git bundle files are intentionally not committed to
this GitHub source repository because the readable extracted contents
and textual forensic reports are already present.

Do not infer missing semantics.

Fail closed when authority is insufficient.
