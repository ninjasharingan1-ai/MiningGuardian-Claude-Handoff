# Mining Guardian — Codex Engineering Instructions

You are implementing **Mining Guardian**, a conservative long-session cryptocurrency mining monitoring and optimization system.

Read this file completely before modifying the project.

Also read `SPEC.md` completely before implementing any feature.

---

# 1. PRIMARY DESIGN PRINCIPLE

The most important rule of this project is:

> Never disrupt a healthy mining session.

A healthy miner must not be restarted, killed, algorithm-switched, or otherwise interrupted because of:

* temporary profitability changes
* optimization attempts
* hashrate noise
* pool calculated-hashrate fluctuations
* AI recommendations
* alternative coin profitability
* temporary API failures

Long-session stability and uptime are first-class optimization objectives.

---

# 2. HARD SAFETY INVARIANTS

These rules must exist in deterministic code.

They must NOT exist only in AI prompts.

The implementation must enforce behavior equivalent to:

```python
HEALTHY_SESSION_RESTART_ALLOWED = False
HEALTHY_SESSION_ALGORITHM_SWITCH_ALLOWED = False

AI_CAN_RESTART_MINER = False
AI_CAN_KILL_MINER = False
AI_CAN_RUN_ARBITRARY_SHELL = False
AI_CAN_CHANGE_WALLET = False
AI_CAN_REQUEST_PAYOUT = False

POOL_CHR_CAN_DRIVE_FAST_OC_LOOP = False
```

The AI advisory layer must never be able to override these rules.

---

# 3. CONTROL OWNERSHIP

The deterministic Mining Guardian Core owns:

* miner health decisions
* hardware safety policies
* experiment approval
* rollback
* session state
* hardware capability validation
* recovery decisions
* process-control authorization

The AI advisory layer does NOT directly own:

* miner process management
* GPU control
* shell execution
* wallet configuration
* payout operations
* live algorithm switching
* emergency recovery

---

# 4. AI PERMISSION POLICY

The AI must never receive unrestricted access to:

```text
shell
PowerShell
cmd.exe
process kill
miner restart
wallet changes
payout controls
raw NVML write access
arbitrary clock changes
algorithm switching
```

The AI should interact only through explicit allowlisted tools.

Initial tools must be read-only.

Examples:

```text
get_session_health()
get_current_metrics()
get_metrics(window)
get_active_profile()
get_verified_profiles()
get_recent_events()
get_recent_experiments()
get_pool_performance()
get_profitability_shadow()
```

Later, proposal-only tools may be added:

```text
propose_experiment()
queue_next_session_candidate()
```

The deterministic core must validate and approve or reject these proposals.

---

# 5. ALLOWED AI ACTION TYPES

AI structured decisions must be limited to actions such as:

```text
NO_ACTION
EXPLAIN_ANOMALY
PROPOSE_EXPERIMENT
FLAG_MAINTENANCE
QUEUE_NEXT_SESSION_CANDIDATE
```

Do not create unrestricted actions such as:

```text
RESTART_NOW
KILL_MINER
SWITCH_ALGORITHM_NOW
SET_CLOCK_RAW
RUN_COMMAND
```

---

# 6. FAST VS SLOW DATA RULE

Fast optimization decisions must use:

```text
SRBMiner local API
NVML telemetry
```

Do NOT use unMineable calculated hashrate as a fast control signal.

unMineable CHR, pool-side metrics, reward accumulation, and worker history are long-horizon validation signals only.

---

# 7. HASHRATE UNIT RULE

All hashrates must be stored internally in:

```text
H/s
```

Do not store internal canonical values in:

```text
MH/s
GH/s
TH/s
```

Conversions are presentation-layer concerns only.

---

# 8. HARDWARE CAPABILITY RULE

Never invent or assume GPU capabilities.

Always probe actual support.

Capability states should include:

```text
SUPPORTED
UNSUPPORTED
NO_PERMISSION
UNKNOWN
```

If NVML or driver functionality is unsupported:

* disable that feature
* log the condition
* continue safely
* do not crash the whole application
* do not fall back to unsafe undocumented commands

---

# 9. HARDWARE WRITE POLICY

Before any hardware write:

```text
policy validation
↓
hardware capability validation
↓
configured user limits
↓
session health validation
↓
hardware write
↓
read-back verification
```

Do not use raw `os.system(...)` hardware-control commands.

All GPU writes must pass through a dedicated hardware-control adapter.

The AI must never call that adapter directly.

---

# 10. EXPERIMENT RULES

Only one hardware parameter may be experimentally changed at a time.

Do not change:

```text
core + memory + power
```

in one experiment.

Use coordinate optimization.

Example:

```text
Phase 1: memory only
Phase 2: core only
Phase 3: power only
```

Every experiment must contain:

* a verified baseline
* one explicit candidate
* a stabilization period
* a measurement period
* explicit acceptance criteria
* explicit rejection criteria
* explicit rollback criteria
* recorded result
* recorded reason

Possible experiment results:

```text
ACCEPT
REJECT
ROLLBACK
INCONCLUSIVE
```

An inconclusive result must never be treated as an improvement.

---

# 11. ROLLBACK POLICY

Always keep these states separate:

```text
best_verified_profile
last_stable_profile
candidate_profile
```

Never overwrite the verified baseline with a degraded measurement.

When a candidate fails:

```text
restore last_stable_profile
```

Rollback triggers may include:

* GPU validation error
* critical temperature event
* persistent hashrate regression
* abnormal reject-rate increase
* driver instability
* hardware write verification failure

---

# 12. ANTI-OSCILLATION RULE

The optimizer must implement:

```text
deadband
cooldown
minimum evidence window
experiment lock
```

Do not allow repetitive unstable behavior like:

```text
+25
-50
+25
-50
```

After rollback, the failed direction or candidate must enter cooldown.

---

# 13. PRODUCTION MODE RULE

Once a good profile is verified, the default objective becomes:

> Protect the session.

Do not continue increasing clocks indefinitely.

New experiments should be rare and controlled.

Do not open a new experiment unless:

```text
session stable long enough
AND no experiment currently active
AND experiment budget allows it
AND health state permits it
```

---

# 14. PROFITABILITY POLICY

The project is NOT a NiceHash-style live switching system.

Profitability must operate in shadow mode during a healthy production session.

Alternative profitability may be:

* measured
* compared
* ranked
* recorded
* recommended for the next session

It must NOT cause:

```text
miner restart
algorithm switch
hardware interruption
```

during a healthy session.

---

# 15. NEXT-SESSION POLICY

Algorithm or strategy changes may be considered only when a session naturally ends, for example:

```text
manual stop
Windows restart
scheduled maintenance
natural miner restart
```

Then the next-session planner may consider profitability recommendations.

---

# 16. FAILURE PHILOSOPHY

External-service failure must fail safe.

If any external component fails:

```text
unMineable unavailable
AI unavailable
SRBMiner API timeout
NVML read failure
network unavailable
database transient issue
```

default behavior should be:

> DO NOTHING THAT INTERRUPTS A HEALTHY MINER.

In particular:

```text
KEEP THE HEALTHY MINER RUNNING
```

Do not restart because monitoring is temporarily unavailable.

---

# 17. EXTERNAL INTEGRATION RULE

Every external integration must sit behind an interface.

Examples:

```text
SRBMinerClient
NVMLClient
UnMineableClient
AIAdvisor
```

Each must have a fake/mock implementation for testing.

Examples:

```text
FakeSRBMinerClient
FakeNVMLClient
FakeUnMineableClient
FakeAIAdvisor
```

---

# 18. TESTING-FIRST RULE

Do not enable live hardware writes before:

* read-only telemetry works
* health detection works
* storage works
* replay works
* rollback logic has tests
* fake adapters exist
* optimizer behavior passes offline tests

Write tests before enabling hardware writes.

---

# 19. REPLAY REQUIREMENT

Any new optimization policy must be testable offline against previously recorded sessions before production use.

Replay should answer:

> What would the optimizer have done?

without touching the real GPU or miner.

---

# 20. SECRETS POLICY

Never hardcode secrets.

Do not write:

```python
API_KEY = "..."
```

inside source code.

Use environment configuration.

Expected secret names may include:

```text
UNMINEABLE_API_KEY=
UNMINEABLE_API_SECRET=
OPENAI_API_KEY=
```

Do not commit real `.env` files.

Provide `.env.example` instead.

---

# 21. LOGGING POLICY

Use structured logging.

Every event should contain as appropriate:

```text
timestamp
event_type
session_id
severity
source
message
metadata
```

Important event types include:

```text
SESSION_STARTED
BASELINE_VERIFIED
EXPERIMENT_STARTED
PROFILE_ACCEPTED
PROFILE_ROLLED_BACK
THERMAL_WARNING
HASHRATE_DROP
POOL_API_ERROR
AI_RECOMMENDATION
```

---

# 22. DEVELOPMENT APPROACH

Implement milestones incrementally.

Do NOT implement the entire project in one pass.

Required progression:

```text
M0
↓
test
↓
M1
↓
validate on real machine
↓
collect real data
↓
M2
↓
test
↓
M3
↓
replay
↓
M4
↓
shadow validation
↓
M5
↓
bounded live tuning
↓
M6+
```

Do not implement a future milestone unless explicitly requested.

---

# 23. MILESTONE BOUNDARIES

## M0 — Skeleton

Allowed:

```text
project structure
configuration
models
logging
tests
CLI
```

No mining control.

---

## M1 — Observe

Implement:

```text
SRBMiner read-only adapter
NVML read-only adapter
SQLite
telemetry collection
session detection
```

Forbidden:

```text
hardware writes
miner restart
miner stop
algorithm switching
AI actions
```

---

## M2 — Pool Intelligence

Implement:

```text
unMineable API client
HMAC authentication where required
worker history
pool-side hashrate
simulator
profitability shadow mode
persistence
```

Still forbidden:

```text
live switching
miner interruption
hardware changes caused by profitability
```

---

## M3 — Guardian

Implement:

```text
health engine
state machine
failure handling
baseline engine
```

---

## M4 — Optimizer Shadow

Implement optimizer decisions in simulation/shadow mode.

No real hardware writes.

---

## M5 — Bounded Live Tuning

Only after M4 is validated.

Allow:

```text
one variable at a time
small configured step
verified capability only
automatic rollback
read-back verification
```

Still forbidden:

```text
live algorithm switching
restart of healthy miner
```

---

## M6 — AI Advisor

Add AI advisory layer using safe tools.

Start read-only.

---

## M7 — Agent-Assisted Experiments

AI may propose experiments.

Deterministic core must approve or reject them.

---

## M8 — Next Session Intelligence

AI/profitability layer may recommend the best next-session candidate.

Do not interrupt current healthy sessions.

---

# 24. FIRST IMPLEMENTATION TASK TEMPLATE

When asked to implement M0 and M1, obey this exact scope:

```text
Read AGENTS.md completely.
Read SPEC.md completely.

Implement M0 and M1 only.

Do not implement hardware writes.
Do not restart, stop, launch, or modify the miner.
Do not implement algorithm switching.
Do not implement AI integration yet.

Build:

1. Python project structure.
2. Typed configuration using Pydantic.
3. Structured logging.
4. SRBMiner read-only client for the local JSON statistics API.
5. NVML read-only capability and telemetry adapter.
6. SQLite persistence.
7. Session and telemetry data models.
8. CLI commands:
   - probe-gpu
   - probe-miner
   - observe
   - status
9. Fake SRBMiner and NVML adapters.
10. Unit and integration tests.

All internal hashrates must use H/s.

The observe command must never modify hardware or miner state.

After implementation:
- run all tests
- run static/type checks if configured
- summarize created files
- report assumptions
- report anything requiring validation on real hardware

Do not proceed to M2.
```

---

# 25. SECOND IMPLEMENTATION TASK TEMPLATE

When explicitly asked to implement M2:

```text
Implement M2 only.

Add the unMineable integration.

Requirements:

- use the official current API
- HMAC-SHA256 authentication where required
- secrets from environment only
- read-only endpoints only
- worker history
- worker/chart data
- simulator
- resilient retries
- rate-limit-safe polling
- SQLite persistence

Build profitability shadow mode.

Profitability results must never cause:
- miner restart
- algorithm switch
- hardware changes

Add tests using mocked API responses.

Do not proceed to M3.
```

---

# 26. CODING QUALITY REQUIREMENTS

Prefer:

* typed Python
* explicit interfaces
* dataclasses or Pydantic models where appropriate
* dependency injection
* small modules
* deterministic logic
* clear domain models
* testable components
* structured exceptions
* clear logging
* asynchronous I/O where justified

Avoid:

* global mutable state
* giant single-file implementations
* raw shell commands
* silent broad exceptions
* hardcoded paths
* hardcoded credentials
* undocumented side effects
* hidden miner process manipulation

---

# 27. IMPORTANT FINAL ENGINEERING PRINCIPLE

The system should behave conceptually as:

```text
Everything healthy?
        │
       YES
        │
        ▼
KEEP MINING
        │
        ├── collect
        ├── analyze
        ├── learn
        └── occasionally run safe bounded experiments

Alternative coin more profitable?
        │
       YES
        │
        ▼
Record it.
Observe it.
Recommend it for next session.

DO NOT INTERRUPT CURRENT SESSION.
```

This principle has priority over aggressive optimization.

# 28. ALGORITHM-AWARE ARCHITECTURE AND DYNAMIC REGISTRY

Mining Guardian must be explicitly algorithm-aware, miner-aware, GPU-aware, and payout-aware.

Do not treat `algorithm` as only an arbitrary string field.

These concepts must remain separate:

```text
GPU
!= Miner Software
!= Mining Algorithm
!= Underlying Mineable Asset / Work
!= Payout Coin
```

The current real workload is PearlPow and must be supported through canonical normalization:

```text
Canonical algorithm: PearlPow
SRBMiner identifier: pearlhash
unMineable/provider identifier: pearlpow
```

The following raw names must resolve to the same canonical algorithm identity:

```text
pearlhash
pearlpow
PearlPow
PEARLPOW
```

PearlPow is the first verified real-world entry, not a hard-coded limitation of the project.

Implement and preserve an `AlgorithmRegistry` abstraction that supports:

```text
algorithm_id
canonical_name
display_name
aliases
miner_specific_names
provider_specific_names
status
source
last_verified_at
optional underlying asset
```

Suggested status concepts:

```text
BUILT_IN
DISCOVERED
VERIFIED
UNKNOWN
DEPRECATED
```

The registry must support built-in algorithms and algorithms first encountered at runtime.

If a miner reports an unknown algorithm:

- preserve the exact raw name
- create or resolve a persistent UNKNOWN/DISCOVERED entry
- continue read-only telemetry collection
- continue session persistence
- log the discovery
- keep it ineligible for optimization until verified
- do not crash
- do not guess its identity
- do not silently map it to another algorithm
- do not restart or switch the miner

The architecture must allow future metadata discovery/enrichment from trusted sources without requiring a Python source-code change for every new algorithm.

Future discovery may load metadata such as:

```text
canonical name
aliases
miner mappings
provider mappings
underlying asset
support status
```

However, automatic discovery must NOT mean automatic downloading or executing miners, mining binaries, plugins, or arbitrary code.

Do not download or execute miner software automatically.

Runtime-discovered algorithms must remain unverified and optimizer-ineligible until explicit validation rules are satisfied.

SRBMiner can expose more than one active algorithm/workload. Do not design miner telemetry around exactly one permanent `algorithm: str` field. A one-algorithm miner should be represented naturally as one workload in a workload collection.

Session and telemetry design must preserve algorithm context so future analytics can distinguish:

```text
GPU + Miner + Algorithm
```

Future profiles and baselines must be isolated by at least:

```text
GPU + Algorithm + Miner
```

and future tuning profiles must never be automatically reused across unrelated algorithms.

All canonical hashrates remain stored in H/s, but raw hashrates from different algorithms must never be ranked directly as if they represented equivalent profitability or efficiency.

This requirement applies from M0/M1 onward as an architectural constraint, even though optimization and profitability are implemented only in later milestones.

