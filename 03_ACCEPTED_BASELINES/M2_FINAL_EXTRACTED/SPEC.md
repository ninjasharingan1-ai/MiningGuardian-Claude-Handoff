# Mining Guardian

## Long-Session Adaptive Mining Optimization Agent

### Technical Product Specification

---

# 1. PROJECT OBJECTIVE

Build a local Windows service/application that monitors, protects, analyzes, and gradually optimizes long-running cryptocurrency mining sessions.

Primary priorities, in order:

```text
1. Session uptime
2. Sustained accepted mining work
3. Stability
4. Hashrate
5. Reward
6. Efficiency
7. Profitability intelligence
```

The system is specifically designed to avoid the behavior of aggressive profitability switchers that continuously restart miners or change algorithms.

Mining Guardian is not a NiceHash-style hopping engine.

---

# 2. CORE PRINCIPLE

The fundamental runtime rule is:

```text
A healthy mining session must never be restarted
or algorithm-switched merely because another option
looks temporarily more profitable.
```

Session continuity has value and must be treated as part of the optimization objective.

---

# 3. HIGH-LEVEL ARCHITECTURE

```text
                     ┌─────────────────────┐
                     │     AI Advisor      │
                     │   reasoning layer   │
                     └─────────┬───────────┘
                               │
                        Safe Tool API
                               │
               ┌───────────────▼───────────────┐
               │        Mining Guardian        │
               │      Deterministic Core       │
               └───────────────┬───────────────┘
                               │
       ┌───────────────────────┼─────────────────────────┐
       │                       │                         │
       ▼                       ▼                         ▼

 SRBMiner Adapter          NVML Adapter            unMineable Adapter
 local miner stats         GPU telemetry           pool / simulator
 accepted/rejected         temperatures            CHR / workers
 RHR / errors              clocks/power            profitability

       │                       │                         │
       └───────────────────────┼─────────────────────────┘
                               ▼

                         SQLite Database

                               │
           ┌───────────────────┼─────────────────────┐
           ▼                   ▼                     ▼

     Session Guardian      Optimizer          Profitability Shadow
```

---

# 4. ARCHITECTURAL RESPONSIBILITIES

## Codex

Codex is the development agent.

Codex:

```text
creates files
writes code
runs tests
refactors
implements milestones
updates documentation
```

Codex is not the runtime mining controller.

---

## Deterministic Core

The deterministic core is responsible for:

```text
session safety
health classification
hardware policy
experiment lifecycle
rollback
recovery rules
state transitions
authorization of actions
```

---

## AI Advisor

The AI layer is responsible for:

```text
diagnosing anomalies
summarizing session behavior
detecting patterns
explaining drops
comparing time periods
recommending experiments
ranking next-session opportunities
identifying maintenance problems
```

The AI is advisory and tool-constrained.

---

# 5. DATA-TIMESCALE MODEL

The system must separate telemetry by timescale.

---

## 5.1 Fast Telemetry

Sources:

```text
NVML
SRBMiner local API
```

Typical interval:

```text
5–30 seconds
```

Used for:

```text
GPU temperature
power
clocks
utilization
local hashrate
miner process state
hardware errors
throttle reasons
```

---

## 5.2 Medium-Term Validation

Sources:

```text
SRBMiner local API
accepted shares
rejected shares
rolling local hashrate statistics
```

Typical horizon:

```text
minutes
```

Used for evaluating overclock or power-profile experiments.

---

## 5.3 Long-Term Validation

Sources:

```text
unMineable
worker history
calculated hashrate
rewards
pool performance
```

Typical horizon:

```text
hours
```

Used for:

```text
long-session validation
pool-side performance
reward analysis
profitability analysis
```

unMineable CHR must NOT drive fast overclock decisions.

---

# 6. PROJECT STRUCTURE

Target structure:

```text
MiningGuardian/
│
├── AGENTS.md
├── SPEC.md
├── README.md
├── pyproject.toml
├── .env.example
├── config.example.yaml
│
├── src/
│   └── mining_guardian/
│       │
│       ├── main.py
│       ├── config.py
│       ├── models.py
│       ├── enums.py
│       │
│       ├── adapters/
│       │   ├── srbminer.py
│       │   ├── nvml.py
│       │   └── unmineable.py
│       │
│       ├── collectors/
│       │   ├── hardware.py
│       │   ├── miner.py
│       │   └── pool.py
│       │
│       ├── core/
│       │   ├── session_guardian.py
│       │   ├── health_engine.py
│       │   ├── state_machine.py
│       │   └── event_bus.py
│       │
│       ├── optimization/
│       │   ├── optimizer.py
│       │   ├── experiment.py
│       │   ├── validator.py
│       │   ├── rollback.py
│       │   └── scoring.py
│       │
│       ├── profitability/
│       │   ├── shadow_engine.py
│       │   └── next_session.py
│       │
│       ├── storage/
│       │   ├── database.py
│       │   ├── schema.py
│       │   └── repository.py
│       │
│       ├── agent/
│       │   ├── tools.py
│       │   ├── advisor.py
│       │   └── schemas.py
│       │
│       └── cli/
│           └── commands.py
│
├── scripts/
│   ├── probe_gpu.py
│   ├── probe_srbminer.py
│   └── export_session.py
│
└── tests/
    ├── unit/
    ├── integration/
    ├── replay/
    └── fixtures/
```

Codex may refine filenames while preserving module separation.

---

# 7. CONFIGURATION

Use typed configuration.

Recommended approach:

```text
Pydantic
Pydantic Settings
environment variables
optional YAML configuration
```

Secrets must come from environment variables.

Example:

```text
UNMINEABLE_API_KEY=
UNMINEABLE_API_SECRET=
OPENAI_API_KEY=
```

Example non-secret configuration:

```text
SRBMINER_API_HOST
SRBMINER_API_PORT

GPU_INDEX

OBSERVE_INTERVAL_SECONDS

EXPERIMENT_STABILIZATION_SECONDS
EXPERIMENT_MEASUREMENT_SECONDS

MAX_CONFIGURED_TEMPERATURE

MEMORY_STEP_MHZ
CORE_STEP_MHZ

OPTIMIZATION_MODE
```

---

# 8. CANONICAL HASHRATE UNIT

Internally, all hashrate values use:

```text
H/s
```

Example:

```text
raw_hs = 27_400_000

H/s  = 27,400,000
MH/s = 27.4
GH/s = 0.0274
```

The database stores:

```text
27_400_000
```

The UI or CLI may format it as:

```text
27.4 MH/s
```

This prevents unit-comparison errors between algorithms.

---

# 9. DATA MODEL

---

## 9.1 hardware_samples

Fields:

```text
timestamp
session_id
gpu_id

temperature_c
utilization_gpu
utilization_memory

core_clock_mhz
memory_clock_mhz

core_offset_mhz
memory_offset_mhz

power_w
power_limit_w

performance_state
throttle_reasons
```

Optional future fields:

```text
fan_percent
fan_rpm
voltage
memory_temperature
hotspot_temperature
```

when available.

---

## 9.2 miner_samples

Fields:

```text
timestamp
session_id

algorithm

local_hashrate_hs

accepted_shares
rejected_shares
invalid_shares

miner_uptime_seconds
gpu_errors
```

---

## 9.3 pool_samples

Fields:

```text
timestamp
session_id

algorithm
reported_hashrate_hs
calculated_hashrate_hs

reward_balance
worker_online
```

---

## 9.4 profiles

Fields:

```text
profile_id
algorithm

core_setting
memory_setting
power_setting

verified
stability_score
median_hashrate_hs
reject_rate
power_mean
temperature_mean

validation_duration
```

---

## 9.5 experiments

Fields:

```text
experiment_id

baseline_profile
candidate_profile

start_time
end_time

result

baseline_score
candidate_score

rollback_reason
```

---

## 9.6 sessions

Fields:

```text
session_id

algorithm
miner
start_time
end_time

natural_restart

best_verified_profile

total_accepted
total_rejected
```

---

# 10. NVML GPU ADAPTER

The NVML adapter is responsible for hardware telemetry.

Read-only telemetry should include when available:

```text
GPU temperature
GPU utilization
memory utilization
GPU clock
memory clock
power draw
power limit
performance state
clock throttle/event reasons
```

Important throttling or event information may include conditions equivalent to:

```text
software power cap
hardware thermal slowdown
software thermal slowdown
hardware power brake
```

The adapter must normalize raw NVML data into internal models.

---

# 11. GPU CAPABILITY PROBE

Before enabling hardware tuning, run a capability probe.

The system should determine:

```text
Can read clocks?
Can set core offset?
Can set memory offset?
Can set power?
Can lock clocks?
Can read temperatures?
Can read throttle reasons?
```

Each capability should be represented as:

```text
SUPPORTED
UNSUPPORTED
NO_PERMISSION
UNKNOWN
```

If unsupported:

```text
disable that feature
continue safely
log the limitation
```

Never assume all RTX 4050 Laptop GPUs or laptop VBIOS configurations expose the same controls.

---

# 12. HARDWARE CONTROLLER

All hardware writes must pass through one explicit component.

Interface concept:

```python
class HardwareController:

    def probe_capabilities(...):
        ...

    def read_state(...):
        ...

    def set_core_offset(...):
        ...

    def set_memory_offset(...):
        ...

    def set_power_limit(...):
        ...

    def restore_verified_profile(...):
        ...
```

Required write pipeline:

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

The AI agent never gets direct access to this component.

---

# 13. SRBMINER INTEGRATION

SRBMiner is the primary fast mining telemetry source.

Use its local statistics API.

The expected local endpoint is typically equivalent to:

```text
http://127.0.0.1:21550
```

when API support is enabled.

The adapter should read:

```text
local hashrate
algorithm
accepted shares
rejected shares
invalid shares
miner uptime
GPU errors
miner health
```

Suggested interface:

```python
class MinerClient:

    async def health(self) -> MinerHealth:
        ...

    async def stats(self) -> MinerStats:
        ...

    async def accepted_shares(self) -> int:
        ...

    async def rejected_shares(self) -> int:
        ...

    async def local_hashrate_hs(self) -> float:
        ...
```

SRBMiner JSON data must be normalized into stable internal models.

---

# 14. SRBMINER STARTUP CONFIGURATION

When appropriate, SRBMiner may later be started with options equivalent to:

```text
--api-enable
--api-rig-name GuardianRig
```

Remote restart, reboot, shutdown, or dangerous remote-control endpoints must not be enabled for this project unless separately designed and secured.

Initial project stages should not launch or alter SRBMiner.

---

# 15. SESSION HEALTH ENGINE

The health engine produces one of:

```text
HEALTHY
WARNING
DEGRADED
FAILED
```

Health must not depend on one metric.

A healthy state should approximately mean:

```text
miner process running
AND local hashrate present
AND no critical GPU error
AND temperatures within configured policy
AND shares continue arriving
AND reject rate acceptable
```

Exact thresholds must be configurable and based on collected real data.

If:

```text
HEALTHY
```

then:

```text
restart forbidden
algorithm switching forbidden
miner kill forbidden
```

---

# 16. SESSION STATE MACHINE

Core state model:

```text
BOOT
 │
 ▼
OBSERVE
 │
 ▼
BASELINE
 │
 ▼
PRODUCTION
 │
 ├─────────► EXPERIMENT
 │                │
 │             VALIDATE
 │             /      \
 │            /        \
 │         ACCEPT    ROLLBACK
 │            │          │
 └────────────┴──────────┘

PRODUCTION
 │
 └──── failure ───► DEGRADED
                         │
                         ▼
                      RECOVERY
```

Additional states may be introduced if they preserve the safety model.

---

# 17. OBSERVE MODE

Observe Mode is the first real runtime mode.

In Observe Mode:

```text
NO clocks changed
NO process restarted
NO algorithm switched
NO hardware write
NO AI control
```

The system only:

```text
reads
records
normalizes
stores
reports
```

Observe Mode must be tested on the real machine before live optimization is enabled.

---

# 18. BASELINE ENGINE

After enough stable observations are collected, compute a baseline.

Baseline statistics may include:

```text
median hashrate
hashrate variance
accepted share rate
reject rate
mean temperature
mean power
throttle occurrence
miner uptime
```

The resulting object becomes:

```text
Verified Baseline
```

No optimizer experiment may start without a verified baseline.

---

# 19. OPTIMIZER DESIGN

Use coordinate optimization.

Do not modify multiple independent variables simultaneously.

Example sequence:

```text
Phase A: Memory optimization
Phase B: Core optimization
Phase C: Power optimization
Phase D: Validation
```

Each phase modifies one variable while holding the others fixed.

---

# 20. EXPERIMENT LIFECYCLE

Example:

```text
Baseline:
memory offset X

Candidate:
memory offset X + configured step
```

Lifecycle:

```text
create candidate
↓
validate safety
↓
apply candidate
↓
stabilization window
↓
measurement window
↓
candidate evaluation
↓
accept / reject / rollback / inconclusive
```

Experiment results:

```text
ACCEPT
REJECT
ROLLBACK
INCONCLUSIVE
```

---

# 21. STATISTICAL VALIDATION

Do not make optimization decisions from a single hashrate reading.

Use rolling statistics.

Potential metrics:

```text
median hashrate
mean hashrate
variance
accepted share rate
reject rate
power mean
temperature mean
throttle-event frequency
```

Example conceptual performance component:

```python
performance =
    median_hashrate_hs * accepted_share_factor
```

Possible penalties:

```text
variance
rejects
validation errors
thermal throttling
power
instability
```

---

# 22. OPTIMIZATION OBJECTIVES

Supported modes may include:

```text
reward_first
efficiency_first
balanced
```

Default for this project:

```text
reward_first
```

However, safety constraints always override objective optimization.

---

# 23. DEAD-BAND AND NOISE HANDLING

The optimizer must distinguish:

```text
noise
real improvement
real degradation
```

Conceptually:

```text
small movement → HOLD
sustained improvement → candidate
sustained degradation → rollback candidate
invalid shares or GPU error → stronger rollback signal
```

Thresholds must not be hardcoded prematurely.

They should become configurable and later be calibrated from real session data.

---

# 24. ROLLBACK ENGINE

Always store separately:

```text
best_verified_profile
last_stable_profile
candidate_profile
```

Failure of a candidate must not redefine the verified baseline.

Rollback restores:

```text
last_stable_profile
```

Possible rollback triggers:

```text
GPU validation error
critical temperature event
persistent hashrate regression
abnormal reject increase
driver instability
hardware write verification failure
```

---

# 25. ANTI-OSCILLATION

Required mechanisms:

```text
deadband
cooldown
minimum evidence window
experiment lock
candidate history
```

The system must prevent continuous back-and-forth adjustments caused by normal hashrate noise.

---

# 26. PRODUCTION MODE

Once a strong stable profile is found:

```text
MODE = PRODUCTION
```

Primary objective becomes:

```text
Protect the session.
```

Production Mode should not continuously overclock.

A new experiment should require:

```text
sufficient stable runtime
no active experiment
experiment budget available
healthy session
safe telemetry
```

---

# 27. UNMINEABLE INTEGRATION

The unMineable adapter is used for:

```text
worker history
pool-side reported hashrate
calculated hashrate
reward monitoring
long-horizon validation
simulator
profitability analysis
```

Where authentication is required, use the official authentication mechanism.

Secrets must come from environment variables.

Prefer read-only permissions.

The project should not expose:

```text
withdrawals
wallet modifications
payout controls
```

to the AI.

---

# 28. UNMINEABLE DATA POLICY

Pool-side CHR is not an immediate hardware-control signal.

Correct conceptual split:

```text
SRBMiner RHR
+
NVML
=
fast feedback
```

while:

```text
unMineable CHR
+
rewards
+
worker history
=
slow validation
```

---

# 29. PROFITABILITY SHADOW ENGINE

The profitability subsystem operates in the background without modifying the current production session.

It evaluates:

```text
current algorithm
alternative algorithm A
alternative algorithm B
...
```

Possible inputs:

```text
stored benchmark hashrate
unMineable simulator
historical stability
historical power
historical reject rate
historical session behavior
```

It must not run disruptive benchmarks during a healthy production session.

Output example:

```text
Current session:
KEEP

Best next-session candidate:
X
```

Even if an alternative becomes temporarily more profitable:

```text
NO LIVE SWITCH
```

---

# 30. NEXT SESSION PLANNER

A new algorithm or profile may be considered after a natural session boundary.

Examples:

```text
manual stop
Windows restart
scheduled maintenance
natural miner restart
```

At this point the planner may evaluate:

```text
current profitability
stored hardware benchmarks
historical stability
expected 24h reward
expected power usage
```

and recommend the next session.

---

# 31. AI AGENT ROLE

The runtime AI is an advisor.

Responsibilities:

```text
diagnose anomalies
summarize session behavior
detect patterns
compare time windows
explain performance changes
recommend safe experiments
rank next-session opportunities
identify maintenance problems
```

The AI should not perform raw device control.

---

# 32. AI TOOL INTERFACE

Initial read-only tools:

```text
get_session_health()

get_current_metrics()

get_metrics(window="1h")

get_metrics(window="24h")

get_active_profile()

get_verified_profiles()

get_recent_events()

get_recent_experiments()

get_pool_performance()

get_profitability_shadow()
```

Later proposal tools:

```text
propose_experiment()

queue_next_session_candidate()
```

---

# 33. AI STRUCTURED OUTPUT

AI responses used programmatically should use structured output.

Example:

```json
{
  "status": "healthy",
  "action": "NO_ACTION",
  "confidence": 0.91,
  "reason": "Session is stable and hashrate variation is within historical range.",
  "suggested_experiment": null
}
```

Allowed actions:

```text
NO_ACTION
EXPLAIN_ANOMALY
PROPOSE_EXPERIMENT
FLAG_MAINTENANCE
QUEUE_NEXT_SESSION_CANDIDATE
```

---

# 34. SQLITE STORAGE

Use SQLite initially.

Requirements:

```text
persistent local history
session records
telemetry samples
hardware samples
miner samples
pool samples
events
experiments
profiles
AI recommendations
```

Database writes must not interfere with miner operation.

Transient storage failures should fail safely.

---

# 35. EVENT SYSTEM

Use structured events.

Event examples:

```text
SESSION_STARTED
SESSION_ENDED
BASELINE_VERIFIED

EXPERIMENT_STARTED
EXPERIMENT_COMPLETED

PROFILE_ACCEPTED
PROFILE_ROLLED_BACK

THERMAL_WARNING
HASHRATE_DROP
SHARE_REJECTION_SPIKE

POOL_API_ERROR
MINER_API_ERROR
NVML_ERROR

AI_RECOMMENDATION
NEXT_SESSION_CANDIDATE
```

---

# 36. LOGGING

Structured log fields should include:

```text
timestamp
event_type
session_id
severity
source
message
metadata
```

Logs should be human-readable and machine-processable.

---

# 37. REPLAY ENGINE

A replay subsystem is required.

It must be able to load a historical session such as:

```text
24 hours
48 hours
72 hours
```

and simulate optimizer behavior offline.

Example command:

```text
python -m mining_guardian replay session_123
```

Replay question:

```text
What would the optimizer have done?
```

Replay must not touch:

```text
real GPU
real miner
real clocks
real processes
```

This is mandatory before introducing new live optimization policies.

---

# 38. FAKE ADAPTERS

Required test doubles:

```text
FakeSRBMinerClient
FakeNVMLClient
FakeUnMineableClient
```

Potential AI fake:

```text
FakeAIAdvisor
```

Use these to simulate:

```text
temperature spike
hashrate collapse
no accepted shares
pool API offline
NVML unsupported
miner crash
clock write rejected
profitability spike
AI unavailable
driver instability
```

without touching the real machine.

---

# 39. FAILURE PHILOSOPHY

If any subsystem becomes unavailable:

```text
unMineable offline
SRBMiner API timeout
NVML unavailable
AI unavailable
network unavailable
```

default behavior:

```text
DO NOTHING DISRUPTIVE
```

If the miner remains healthy:

```text
KEEP MINING
```

Monitoring failure must not automatically become mining failure.

---

# 40. RECOVERY

Recovery is separate from optimization.

Restart may be considered only after the session becomes genuinely failed or unrecoverable.

Potential evidence:

```text
miner process dead
GPU unavailable
persistent zero accepted shares
persistent zero local hashrate
critical miner error
driver failure
```

Recovery decisions must belong to deterministic code.

---

# 41. SECURITY AND SECRETS

Do not hardcode:

```text
API keys
wallet secrets
OpenAI keys
unMineable secrets
```

Provide:

```text
.env.example
```

Actual `.env` must be excluded from source control.

The AI should not have access to secrets unless absolutely necessary.

---

# 42. CLI

Initial CLI should support:

```text
probe-gpu
probe-miner
observe
status
```

Later commands may include:

```text
replay
export-session
show-profile
show-events
shadow-profitability
```

CLI commands must make side effects explicit.

Observe commands must remain read-only.

---

# 43. MILESTONE PLAN

---

## M0 — Project Skeleton

Build:

```text
project structure
configuration
models
logging
tests
CLI foundation
```

No mining logic.

---

## M1 — Observe

Build:

```text
SRBMiner read-only adapter
NVML read-only adapter
SQLite persistence
telemetry collection
session detection
CLI:
  probe-gpu
  probe-miner
  observe
  status
fake adapters
unit tests
integration tests
```

No hardware writes.

No process modification.

---

## M2 — Pool Intelligence

Build:

```text
unMineable integration
authentication
worker history
pool data
calculated hashrate history
reward data
simulator
profitability shadow engine
SQLite persistence
API retry handling
rate-limit-safe polling
mocked tests
```

No switching.

---

## M3 — Guardian

Build:

```text
health engine
state machine
failure handling
baseline engine
session protection rules
```

---

## M4 — Optimizer Shadow

Build optimizer logic without hardware writes.

The optimizer analyzes historical and live data and records:

```text
what it would have changed
why
expected result
rollback condition
```

but changes nothing.

---

## M5 — Bounded Live Tuning

Only after M4 validation.

Enable:

```text
one variable at a time
small configured steps
verified hardware capabilities
read-back verification
automatic rollback
cooldowns
experiment budget
```

No live algorithm switching.

No healthy-session restart.

---

## M6 — AI Advisor

Add the AI advisory layer.

Start with read-only tools.

The AI should:

```text
analyze
summarize
diagnose
recommend
```

but not directly control hardware.

---

## M7 — Agent-Assisted Experiments

Allow AI to call:

```text
propose_experiment()
```

The deterministic core decides whether it is safe and allowed.

---

## M8 — Next Session Intelligence

Combine:

```text
historical performance
algorithm benchmarks
profitability
reward history
power usage
session stability
```

to recommend:

```text
best next-session algorithm/profile
```

without interrupting the current session.

---

# 44. DEFINITION OF DONE

Do not consider the project production-ready before all of these are true:

```text
24h Observe session without interference

No miner restart caused by Guardian during healthy mining

Pool API outage does not affect miner

AI outage does not affect miner

NVML failure does not affect miner

Bad candidate reliably rolls back

Replay system reproduces optimizer decisions

No unrestricted shell exposed to AI

Healthy session cannot be algorithm-switched

All hashrates normalized internally to H/s
```

---

# 45. FIRST REAL-MACHINE VALIDATION

The first real-machine run must be:

```text
OBSERVE ONLY
```

Recommended initial duration:

```text
12–24 hours
```

During this stage record:

```text
SRBMiner local hashrate
accepted shares
rejected shares
GPU temperature
GPU clocks
GPU utilization
power
throttle reasons
session uptime
```

Do not modify the GPU.

Do not modify the miner.

Do not introduce AI control yet.

---

# 46. DEVELOPMENT SEQUENCE

Correct implementation order:

```text
Create project
↓
M0 skeleton
↓
M1 observe
↓
Validate real telemetry
↓
Collect 12–24h data
↓
M2 unMineable
↓
M3 guardian
↓
Replay engine
↓
M4 optimizer shadow
↓
Validate offline behavior
↓
M5 bounded tuning
↓
Collect real optimization data
↓
M6 AI advisor
↓
M7 proposals
↓
M8 next-session intelligence
```

Do not start with the AI.

The AI becomes useful only after the system has reliable telemetry and deterministic safety.

---

# 47. INITIAL DEPENDENCIES

Initial Python dependencies may include:

```text
pydantic
pydantic-settings
httpx
sqlalchemy
nvidia-ml-py
psutil
tenacity
structlog
pytest
pytest-asyncio
```

Additional dependencies should be introduced only when justified.

---

# 48. PYTHON ENVIRONMENT

Recommended environment:

```text
Python 3.12+
virtual environment
Windows
VS Code
Codex
```

Typical project environment:

```text
C:\MiningGuardian
```

Virtual environment:

```text
C:\MiningGuardian\.venv
```

---

# 49. RUNTIME PHILOSOPHY

The final runtime should conceptually behave like this:

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
        └── occasionally run safe bounded experiment

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

---

# 50. FINAL PRODUCT VISION

Mining Guardian should ultimately behave as a:

```text
Long-Session Adaptive Mining Agent
```

rather than an aggressive miner switcher.

Its intelligence should come from the relationship between:

```text
uptime
local hashrate
pool-side hashrate
accepted shares
rejected shares
temperature
power
clock behavior
throttling
reward
historical stability
profitability
```

The goal is not simply:

```text
What is the highest-paying algorithm right now?
```

The goal is:

```text
What action is most likely to maximize realized reward
over the next 24 / 48 / 72 hours
without sacrificing a healthy long-running session?
```

# 51. ALGORITHM-AWARE ARCHITECTURE AND DYNAMIC REGISTRY

Mining Guardian must treat the mining algorithm as a first-class domain concept rather than a simple text label.

The domain model must keep the following separate:

```text
GPU
Miner Software
Mining Algorithm
Underlying Mineable Asset / Work
Payout Coin
```

No component may infer one of these from another unless an explicit verified mapping exists.

---

## 51.1 Current Real Workload: PearlPow

The current production mining workload uses PearlPow.

Verified naming relationship:

```text
Canonical algorithm: PearlPow
SRBMiner name: pearlhash
unMineable/provider name: pearlpow
```

Normalization must treat the following as aliases of one canonical identity:

```text
pearlhash
pearlpow
PearlPow
PEARLPOW
```

The PearlPow mapping must be supplied through the algorithm registry and not hard-coded into SRBMiner parsing logic.

PearlPow is a seed entry and test case. The system must not be limited to PearlPow.

---

## 51.2 Algorithm Registry

Create a persistent `AlgorithmRegistry` abstraction.

Each algorithm record should be able to represent:

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
optional underlying_asset
optimizer_eligibility
```

Suggested statuses:

```text
BUILT_IN
DISCOVERED
VERIFIED
UNKNOWN
DEPRECATED
```

The implementation may refine exact field names while preserving the semantics.

The registry should allow algorithms to be added or enriched without editing Python source code for every new algorithm.

Suitable persistence approaches include SQLite-backed registry data or seed data plus persisted overrides.

---

## 51.3 Runtime Discovery of Unknown Algorithms

If SRBMiner or another future miner reports an unknown algorithm, Mining Guardian must:

```text
preserve the exact raw name
create/resolve a persistent UNKNOWN or DISCOVERED entry
continue collecting telemetry
continue storing the session
log an algorithm-discovery event
keep the algorithm optimizer-ineligible
```

It must not:

```text
crash
guess the identity
silently alias it to an unrelated algorithm
restart the miner
switch algorithms
benchmark automatically
change GPU settings
download a miner or executable
execute arbitrary downloaded code
```

Unknown algorithm detection is not a session failure.

The discovered entry must survive application restart.

---

## 51.4 Future Metadata Loading / Enrichment

Later milestones may enrich unknown algorithms from trusted metadata sources.

The architecture must support loading metadata such as:

```text
canonical name
aliases
miner-specific identifiers
provider-specific identifiers
underlying asset
support state
algorithm family / characteristics
```

This is metadata discovery, not executable-code acquisition.

Mining Guardian must never automatically download or run miners, binaries, plugins, or arbitrary executables merely because it encountered an unknown algorithm.

A newly discovered algorithm must remain unverified until validation is complete.

Only verified algorithms may later become eligible for optimizer or profitability logic.

---

## 51.5 Multi-Algorithm Miner Support

Do not assume one miner process permanently maps to one algorithm.

SRBMiner can expose multiple algorithm workloads, so the telemetry model must allow a miner snapshot to contain one or more algorithm workload entries.

Conceptual model:

```text
MinerSnapshot
  miner identity
  uptime
  algorithm_workloads[]
```

Each workload may include when available:

```text
raw_algorithm_name
canonical_algorithm_id
hashrate_hs
accepted_shares
rejected_shares
invalid_shares
device/GPU association
```

A single-algorithm session is simply a snapshot containing one workload.

---

## 51.6 Algorithm-Aware Sessions and Telemetry

Session and telemetry persistence must preserve enough context to distinguish:

```text
same GPU + same miner + different algorithm
same GPU + different miner + same algorithm
multiple algorithms reported by one miner
```

Miner telemetry must retain canonical and raw algorithm identity where useful.

Hardware telemetry must be correlatable to the active session/device/workload context.

This must allow future queries such as:

```text
How did this RTX 4050 behave with SRBMiner while running PearlPow?
```

without mixing those samples with unrelated algorithms.

---

## 51.7 Future Baseline and Profile Isolation

Future baselines must be isolated by at least:

```text
GPU + Algorithm + Miner
```

Future tuning profiles must be scoped by:

```text
GPU + Algorithm + Miner + Profile
```

A profile learned for PearlPow must never automatically become a profile for KawPow, XelisHash, FishHash, or another workload.

M0/M1 should prepare the models/schema for this requirement without enabling live tuning.

---

## 51.8 Hashrate Context

All canonical internal hashrates remain stored in H/s.

However, hashrates from different algorithms must not be ranked directly by magnitude.

For example:

```text
10 MH/s on Algorithm A
5 MH/s on Algorithm B
```

is not sufficient evidence that Algorithm A is more profitable, efficient, or desirable.

Cross-algorithm decisions in later milestones must use algorithm-aware benchmark, reward, power, stability, and pool data.

---

## 51.9 Payout Coin Separation

Payout coin is an independent optional configuration/domain field.

Example:

```text
Mining algorithm: PearlPow
Payout coin: DOGE
```

The algorithm must not be inferred from the payout coin, and the payout coin must not be inferred from the miner.

M0/M1 treats payout coin as metadata only.

No wallet modification or payout action belongs in M0/M1.

---

## 51.10 Required Algorithm Tests

M0/M1 tests must eventually cover:

```text
pearlhash -> PearlPow
pearlpow -> PearlPow
case-variant normalization
unknown algorithm preservation
unknown algorithm persistence across restart
unknown algorithm telemetry collection
unknown algorithms remain optimizer-ineligible
same canonical algorithm from miner/provider-specific aliases
same GPU/miner with different algorithms remains distinguishable
multiple algorithm workloads in one miner snapshot
payout coin remains separate from algorithm identity
no generic cross-algorithm ranking by raw hashrate
```

These requirements do not authorize M2, benchmarking, switching, live optimization, or executable downloads.

