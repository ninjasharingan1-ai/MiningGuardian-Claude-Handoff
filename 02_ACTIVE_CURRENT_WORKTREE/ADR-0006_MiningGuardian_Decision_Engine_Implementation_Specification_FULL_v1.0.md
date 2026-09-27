# ADR-0006

# MiningGuardian Decision Engine Implementation Specification FULL v1.0

## M2.2.2 Implementation Specification

**Source:** ADR-0006 v0.1 → v0.7\
**Status:** Full consolidated architecture document\
**Purpose:** Preserve the complete decision-engine specification without
removing technical details.

------------------------------------------------------------------------

ADR-0006 MiningGuardian Decision Engine Specification

Status: Draft Phase: M2.2.2 Category: Cognitive Architecture / Decision
Intelligence Supersedes: Informal optimization logic Depends on: M2.2.1
Evidence Foundation

1.  Decision

MiningGuardian SHALL operate as a probabilistic decision engine rather
than a direct optimization controller.

The system SHALL NOT optimize based on a single metric such as:

Reported Hashrate Instant Efficiency Current Pool Difficulty Single
Share Event

Instead, all operational decisions SHALL be based on:

Expected Net Reward Improvement adjusted by confidence, risk, and
intervention cost.

2.  Problem Definition

Traditional mining optimization systems follow:

Observe GPU ↓ Change Setting ↓ Measure Hashrate ↓ Keep/Revert

MiningGuardian rejects this model.

The system recognizes that:

Reported Performance ≠ Economic Performance

because mining outcome depends on:

Effective submitted work Share acceptance behavior Pool latency Network
conditions Thermal stability Power constraints Intervention cost

Therefore the core question becomes:

"Will this decision increase expected long-term reward under current
uncertainty?"

3.  Core Decision Model

The Decision Engine SHALL evaluate every candidate action using:

Decision Value = Expected Benefit - Action Cost - Risk Penalty

Where:

Expected Benefit

Represents estimated improvement:

Expected Reward Gain = (Current Expected Reward) - (Baseline Expected
Reward) Action Cost

Includes:

Restart Cost + Warmup Loss + Connection Loss + Instability Risk +
Recovery Time Risk Penalty

Includes:

Thermal Risk + Hardware Risk + Evidence Uncertainty + Prediction Error
4. Decision Engine Pipeline

The engine SHALL follow this sequence:

Telemetry Collection

        ↓

Evidence Validation

        ↓

State Estimation

        ↓

Hypothesis Generation

        ↓

Candidate Evaluation

        ↓

Decision Scoring

        ↓

Action Authorization

        ↓

Result Verification

No action may bypass this pipeline.

5.  Evidence Layer Dependency

Decision Engine SHALL NOT directly consume raw telemetry.

Raw signals:

GPU Temperature Clock Speed Power Hashrate Accepted Shares Rejected
Shares Latency

must first become:

Validated Evidence Objects

Example:

Raw:

Hashrate dropped from 42TH/s to 39TH/s

is insufficient.

Evidence:

Hashrate decline detected

Confidence: 0.82

Supporting signals:

-   Accepted share rate decreased
-   Pool latency increased
-   GPU clock unchanged
-   Power stable

Likely cause: Network degradation 6. State Representation

MiningGuardian SHALL maintain a continuous internal state:

MiningState { GPU_State

Network_State

Pool_State

Thermal_State

Economic_State

Confidence_State }

Example:

GPU_State:

Core Clock: 2035 MHz

Power: 50W

Thermal: Stable

Throttle: False

Confidence: High 7. Candidate Action Model

Every possible action SHALL be represented as:

CandidateAction { ID

Type

ExpectedGain

ExpectedCost

Confidence

Risk

Reversible

RequiredDowntime }

Examples:

Action:

Switch pool endpoint

Expected Gain: +3%

Cost: 20 seconds downtime

Confidence: 0.75

Decision Engine evaluates:

Gain \> Cost + Risk ? 8. Five-Minute Decision Cycle

Five minutes SHALL represent:

Decision Evaluation Window

Not:

Complete Statistical Truth Window

The engine uses multiple horizons:

5 min Current condition

15 min Short trend

60 min Baseline comparison

Long-term Learning model 9. Intervention Threshold

MiningGuardian SHALL avoid unnecessary actions.

An action is permitted only when:

Expected Improvement

Minimum Required Improvement

The threshold depends on:

Action cost Confidence Risk

Example:

Low-cost action:

Change monitoring parameter

Required gain: 0.5%

High-cost action:

Miner restart

Required gain: \>3-5% 10. Restart Policy

Miner restart SHALL be considered a high-cost action.

Restart requires:

Expected Gain

Restart Cost

-   

Safety Margin

The system SHALL avoid:

Frequent restarts Oscillation between configurations Reacting to
temporary noise 11. Decision Classes

All decisions SHALL belong to one of:

HOLD

No intervention.

Reason:

Current state acceptable MONITOR

Continue observation.

Reason:

Evidence insufficient ADJUST

Apply reversible optimization.

Example:

Power target Clock profile Pool parameter RECOVER

Execute corrective action.

Example:

Miner restart Connection recovery LEARN

Record event for future models.

12. Failure Prevention Rules

Decision Engine MUST prevent:

Hashrate obsession

Rejected:

Highest Hashrate = Best Decision Short-term reaction

Rejected:

One bad minute = Action Exploration without reward model

Rejected:

Try everything Restart loops

Rejected:

Optimize → Restart → Optimize → Restart 13. Success Metrics

MiningGuardian success SHALL be measured by:

Primary:

Expected Net Reward / Time

Secondary:

Reward Stability

Energy Efficiency

Uptime

Decision Accuracy

False Intervention Rate 14. Architectural Principle

The Decision Engine SHALL prefer:

Correct Inaction

over:

Incorrect Optimization

A system that knows when NOT to act is considered more intelligent than
a system that constantly modifies parameters.

15. Implementation Boundary

M2.2.2 SHALL implement:

✓ Decision models ✓ Scoring system ✓ Candidate evaluation ✓ Confidence
calculation ✓ Action authorization rules

M2.2.2 SHALL NOT implement:

✗ Automatic overclocking ✗ Miner control ✗ Pool switching ✗ Hardware
modification

Those belong to later execution layers.

Final Principle

MiningGuardian is not a controller that changes mining parameters.

It is a cognitive layer that decides:

"Is intervention economically justified, technically safe, and supported
by sufficient evidence?"

Only after answering YES may the execution layer act.

هذه هي Draft v0.1 للـ ADR-0006 / M2.2.2.

الخطوة التالية المنطقية قبل كتابة الكود هي تطويرها إلى v0.2 بإضافة:

Decision scoring formula بشكل رياضي كامل Confidence engine State machine
diagram JSON schemas للـ Evidence / CandidateAction / Decision objects

------------------------------------------------------------------------

التطوير الأساسي سيكون في 4 محاور:

Decision Mathematical Model Confidence & Uncertainty Engine Decision
State Machine Data Contracts / Schemas

سأكتبها كوثيقة هندسية.

ADR-0006 v0.2 MiningGuardian Decision Engine Specification

Status: Draft v0.2 Milestone: M2.2.2 Purpose: Define the mathematical
and architectural foundation of autonomous mining decisions.

1.  Decision Engine Objective

The Decision Engine exists to answer one question:

"Given the current mining reality, available evidence, possible actions,
and uncertainty, is there a decision that improves expected mining
outcome enough to justify the associated risk and cost?"

The engine does not optimize a single variable.

It optimizes:

$$ Maximum\ Sustainable\ Effective\ Reward $$ 2. Core Optimization
Function

Every candidate decision receives a score.

Decision Utility Score (DUS) $$ DUS = (B \times C) - (R + A + U) $$

Where:

B --- Expected Benefit

Expected improvement from the action.

Components:

$$ B = RewardGain + EfficiencyGain + StabilityGain $$

Example:

{ "reward_gain": 0.04, "efficiency_gain": 0.02, "stability_gain": 0.01 }

Total:

Benefit = +7% C --- Confidence Factor

Represents how trustworthy the prediction is.

Range:

0.0 → 1.0

Example:

Confidence = 0.85

Meaning:

85% confidence that the expected improvement is real.

R --- Risk Penalty

Represents possible negative outcomes.

Components:

$$ R = HardwareRisk + MiningRisk + EconomicRisk $$

Example:

{ "hardware":0.1, "mining":0.05, "economic":0.1 } A --- Action Cost

Cost of performing the action.

Includes:

downtime restart cost lost shares warmup period connection disruption

Example:

Pool switch:

Action Cost = 0.03 U --- Uncertainty Penalty

Unknown information.

Example:

Low evidence: U = 0.4

Strong evidence: U = 0.05 3. Expected Reward Model

MiningGuardian does not use hashrate alone.

The economic model:

$$ ERR = (Expected\ Reward) - (Energy Cost) - (Risk Cost) $$

Where:

Expected Reward
$$ ExpectedReward = BlockReward \times ProbabilityContribution \times PoolEfficiency $$
Probability Contribution

Depends on:

effective hashrate network difficulty algorithm conditions

Conceptually:

$$ P = \frac{MinerHashrate} {NetworkHashrate} $$ Pool Efficiency

Includes:

latency stale shares rejected shares pool reliability 4. Five-Minute
Evaluation Model

The engine evaluates decisions every five minutes.

However:

The five-minute cycle is not the only memory.

The system uses:

Current Window \| \| Short Trend (15 minutes) \| \| Operational Baseline
(1 hour) \| \| Long-Term Learning (days) 5. Confidence Engine

No decision can exist without confidence.

Confidence is calculated from:

$$ Confidence = EvidenceQuality \times DataFreshness \times ModelAgreement $$
Evidence Quality

Factors:

source reliability measurement accuracy signal consistency

Example:

NVML:

High reliability

User assumption:

Low reliability Freshness

Example:

0-30 seconds: Fresh

30-120 seconds: Recent

> 120 seconds: Stale Model Agreement

If multiple models agree:

Confidence increases.

Example:

Thermal issue:

Evidence:

Temperature ↑ Power ↑ Clock throttling ↑ Hashrate ↓

Confidence:

High.

6.  Decision State Machine

The engine follows:

UNKNOWN

    |
    v

OBSERVE

    |
    |

Enough Evidence? \| v

EVALUATE

    |
    |

Calculate Utility Score

    |
    v

DECIDE

/ \|\

HOLD TEST ACTION

7.  Decision States UNKNOWN

Insufficient information.

Allowed:

collect data wait OBSERVE

A change was detected.

Example:

Hashrate decreased 3%

No action yet.

EVALUATE

System generates:

hypotheses candidate actions predicted outcomes HOLD

Current state is acceptable.

Example:

No action improves expected reward. TEST

Controlled experiment.

Example:

Try lower power profile.

Requirements:

reversible measurable safe ACTION

Future execution layer only.

M2.2.2 produces proposals.

It does not execute.

8.  Candidate Action Schema

Every possible action:

{ "id":"action_pool_change_01",

"type":"POOL_CHANGE",

"expected_gain":0.04,

"confidence":0.82,

"risk":0.15,

"cost":0.03,

"reversible":true,

"requires_validation":true } 9. Decision Object Schema

The output of the Decision Engine:

{ "decision_id":"dec_001",

"state":"EVALUATE",

"objective": "maximize effective reward",

"evidence":\[ "hashrate_drop", "latency_increase"\],

"hypotheses":\[ "pool_degradation"\],

"candidate_actions":\[ "switch_pool", "remain_current"\],

"selected_option": "remain_current",

"confidence":0.78,

"reason":

"Expected improvement does not exceed switching cost",

"execution":

"NOT_EXECUTED" } 10. Safety Constraints

The Decision Engine MUST reject:

Low confidence actions

Example:

Expected gain 5% Confidence 0.3

Result:

NO ACTION

High disruption actions

Example:

Restart miner

Expected gain: 1%

Rejected.

Hardware risk actions

Example:

Higher power

Temperature margin insufficient

Rejected.

11. Learning Loop

Every decision creates:

Decision

↓

Observed Result

↓

Comparison:

Prediction vs Reality

↓

Model Update

Example:

Prediction:

Pool change: +5%

Reality:

+1%

Learning:

Reduce confidence for similar future predictions.

12. M2.2.2 Implementation Boundary

M2.2.2 SHALL implement:

✅ Decision models ✅ Scoring engine ✅ Confidence calculation ✅
Candidate ranking ✅ Decision journal integration ✅ Simulation only

M2.2.2 SHALL NOT implement:

❌ Miner control ❌ Pool switching ❌ GPU modification ❌ Automatic
execution

Final Principle

MiningGuardian does not ask:

"What action gives the highest number?"

It asks:

"What decision maximizes expected sustainable reward while respecting
uncertainty, hardware limits, and operational continuity?"

------------------------------------------------------------------------

ADR-0006 v0.3 MiningGuardian Decision Engine Specification Decision
Ranking & Selection Architecture

Status: Draft v0.3 Milestone: M2.2.2 Purpose: Define how MiningGuardian
evaluates, ranks, and selects decisions under uncertainty.

13. Decision Ranking Engine 13.1 Purpose

The Decision Ranking Engine is responsible for answering:

"Given multiple possible actions, which option provides the highest
expected value while maintaining safety and continuity?"

The engine does not search for:

Highest performance

It searches for:

Highest risk-adjusted expected outcome 14. Candidate Decision Ranking
Model

Every candidate action receives a normalized score:

$$ DecisionScore = (B \times C) - (R + A + U) $$

Where:

Benefit Score (B)

Represents expected positive impact.

Components:

$$ B = W_r R_g + W_e E_g + W_s S_g $$

Where:

Symbol Meaning Rg Reward gain Eg Efficiency gain Sg Stability gain W
Importance weight

Example:

Candidate:

Pool Change

Expected:

Reward: +5%

Efficiency: +1%

Stability: -2%

The system does not see +5% only.

It calculates the combined impact.

15. Confidence Weighting

A decision with high theoretical gain but low confidence is downgraded.

Example:

Decision A Expected Gain: +10%

Confidence: 0.3

Effective value:

10 × 0.3 = 3 Decision B Expected Gain: +5%

Confidence: 0.9

Effective value:

5 × 0.9 = 4.5

Decision B becomes preferable.

16. Risk Adjustment Model

Risk is not a single value.

It is divided into:

Hardware Risk

Factors:

temperature increase power increase thermal margin reduction GPU error
probability

Example:

Power +10W Temperature +8C

Hardware Risk: High Mining Risk

Factors:

rejected shares stale shares connection instability miner interruption
Economic Risk

Factors:

uncertain reward volatile conditions insufficient historical evidence
17. Decision Ranking Example

Current state:

PearlPow 40 TH/s 50W 71C

Available options:

Option A

Increase power:

Expected: +5% hashrate

Cost: +8W

Risk: Medium Option B

Reduce power:

Expected: -2% hashrate

Cost: -8W

Risk: Low Option C

No change:

Expected: 0%

Risk: None

The engine evaluates:

A: Benefit - Risk = Positive/Negative

B: Benefit - Efficiency Gain

C: Baseline preservation

The winner is not automatically A.

18. No-Action Decision as First-Class Option

Important architectural decision:

NO_ACTION is always included as a candidate.

The engine always compares:

Current State

against:

Possible Changes

Example:

{ "candidate":"NO_ACTION", "expected_gain":0, "risk":0, "cost":0 }

This prevents unnecessary optimization loops.

19. Decision Thresholds

A candidate action requires:

Minimum Utility Gain

Example:

Expected Score Improvement \> 5%

Otherwise:

HOLD

Threshold depends on action type.

Low Risk Action

Example:

Change monitoring parameter.

Threshold:

Small improvement acceptable High Risk Action

Example:

Miner restart.

Threshold:

Large improvement required 20. Action Cost Model

Every action has a transition cost.

Formula:

$$ NetDecisionValue = DecisionScore - TransitionCost $$

Transition cost includes:

Downtime

Lost shares

Connection recovery

Warmup

Probability of failure

Example:

Pool switch:

Expected improvement:

+3%

Cost:

2 minutes downtime

Result:

Reject

because the gain cannot recover the loss.

21. Decision Tie Breaking

Sometimes multiple options have similar scores.

Example:

Option A: Score 0.81

Option B: Score 0.79

The system follows:

Lower risk wins Higher confidence wins Lower intervention cost wins More
reversible option wins

Priority:

Safety ↓ Confidence ↓ Continuity ↓ Reward ↓ Efficiency 22. Decision
Explanation Requirement

Every decision must be explainable.

The engine must produce:

{ "decision":"HOLD",

"reason": "Alternative actions do not exceed current expected reward",

"evidence":\[ "stable_hashrate", "acceptable_temperature"\],

"confidence":0.91,

"rejected_options":\[ { "option":"increase_power", "reason":"risk
exceeds expected gain" }\] } 23. Decision Memory Integration

Every ranked decision creates a learning record:

Decision

↓

Prediction

↓

Actual Result

↓

Prediction Error

↓

Future Adjustment

Example:

Prediction:

Pool switch: +5%

Reality:

+1%

The model adjusts future confidence.

24. Decision Engine Output Contract

M2.2.2 SHALL output:

{ "state":"DECIDED",

"selected_action":"HOLD",

"score":0.82,

"confidence":0.9,

"evidence_ids":\[ "ev_001", "ev_002"\],

"alternatives_ranked":\[ { "name":"pool_switch", "score":0.41 }, {
"name":"power_adjustment", "score":0.32 }\],

"execution_allowed":false } 25. M2.2.2 Final Architecture After v0.3

The complete cognitive flow becomes:

WORLD STATE

      ↓

EVIDENCE ENGINE

      ↓

HYPOTHESIS ENGINE

      ↓

CANDIDATE GENERATION

      ↓

DECISION SCORING

      ↓

DECISION RANKING

      ↓

DECISION RECORD

      ↓

(Future) CONTROL LAYER 26. Core Philosophy v0.3

MiningGuardian does not ask:

"What can I change?"

It asks:

"Among all possible choices, including doing nothing, which choice has
the highest probability of improving sustainable mining reward?"

------------------------------------------------------------------------

ADR-0006 v0.4 MiningGuardian Decision Engine Specification Candidate
Generation, Prediction & Experiment Architecture

Status: Draft v0.4 Milestone: M2.2.2 Purpose: Define how MiningGuardian
discovers optimization opportunities, predicts outcomes, and validates
decisions.

27. Candidate Generation Engine 27.1 Purpose

The Decision Engine SHALL NOT randomly search for improvements.

It SHALL generate candidate decisions from:

Observed deviations Historical patterns Mathematical models Known
optimization spaces

The system moves from:

"What can I change?"

to:

"What evidence indicates that a change may improve expected reward?" 28.
Candidate Generation Sources

Candidate actions may originate from four sources.

Source 1 --- Performance Deviation Detection

The system compares current state against expected baseline.

Example:

Baseline:

Expected:

40 TH/s 50W 70°C

Current:

38 TH/s 50W 71°C

Detected:

Performance degradation

Possible candidates:

Investigate thermal behavior

Investigate pool efficiency

Investigate miner state Source 2 --- Efficiency Opportunity Detection

The system searches for inefficient operating points.

Example:

Historical memory:

Profile A

40 TH/s 50W

Profile B

39.5 TH/s 42W

The engine may generate:

{ "type":"EFFICIENCY_OPTIMIZATION",

"candidate": "evaluate lower power profile" } Source 3 --- Network
Opportunity Detection

The system evaluates mining environment.

Signals:

Pool latency Stale shares Rejected shares Job frequency Reward
efficiency

Example:

Current:

Pool A

Latency: 180ms

Rejected: 2%

Alternative:

Pool B

Latency: 40ms

Rejected: 0.2%

Candidate:

Evaluate pool change Source 4 --- Historical Learning

Past successful decisions become future candidates.

Example:

Memory:

When:

Temperature \>75C

and

Hashrate decreases

Previous solution:

Reduce power target

Result:

+3% effective reward

Future:

The system can propose the same hypothesis.

29. Candidate Generation Rules

Candidate generation SHALL obey:

No Evidence = No Candidate

The system cannot generate:

Increase power

without evidence that:

power is limiting performance thermal margin exists expected reward
improves No Historical Support = Low Priority

New ideas are allowed but receive lower confidence.

Dangerous Actions Require Higher Evidence

Example:

Changing power:

Evidence threshold:

Medium

Changing voltage:

Evidence threshold:

High

30. Predictive Evaluation Layer

Before ranking an action, MiningGuardian predicts:

"What is likely to happen if this decision is applied?"

Prediction Model

Concept:

$$ FutureState = f(CurrentState, Action, HistoricalExperience) $$

Inputs:

Current GPU state

Current mining state

Network state

Historical outcomes

Candidate action

Output:

{ "predicted_hashrate":42,

"predicted_power":48,

"predicted_reward":1.05,

"confidence":0.76 } 31. Prediction Horizons

The system predicts multiple horizons:

Immediate

Seconds to minutes:

Thermal response Connection impact Short term

5-30 minutes:

Reward improvement Share behaviour Long term

Hours/days:

Stability Hardware impact Efficiency trend 32. Mathematical Modelling
Layer

The engine uses multiple models rather than one prediction.

Model A --- Efficiency Model
$$ Efficiency = \frac{EffectiveHashrate}{Power} $$

Used for:

Power decisions Clock evaluation Model B --- Reward Model
$$ ExpectedReward = f( EffectiveHashrate, BlockReward, Difficulty, PoolEfficiency ) $$
Model C --- Stability Model

Measures:

Variance

Failures

Thermal behaviour

Reject rate Model D --- Confidence Model

Measures:

Prediction accuracy history

Evidence quality

Data availability 33. Controlled Experiment Framework

MiningGuardian SHALL learn through controlled experiments.

Not:

Change everything

But:

Hypothesis

↓

Single Variable Change

↓

Measure Result

↓

Accept / Reject 34. Experiment Object

Example:

{ "id":"exp_001",

"hypothesis":

"Lower power improves TH/W without reducing reward",

"baseline":

{ "hashrate":40, "power":50 },

"change":

{ "power_limit":45 },

"metrics":

\[ "effective_hashrate", "reward_rate", "temperature"\],

"duration":

"30 minutes" } 35. Experiment Safety Rules

Experiments MUST be:

Reversible

The system must know how to return.

Isolated

One variable only.

Measurable

Clear success criteria.

Bounded

Maximum duration.

36. Prediction vs Reality Learning

After every experiment:

Compare:

Prediction:

Expected:

+5% reward

Reality:

Actual:

+1.5%

Calculate:

$$ PredictionError = |Expected-Actual| $$

Store:

{ "prediction_error":0.035,

"future_confidence_adjustment":-0.1 } 37. Decision Learning Loop

The complete loop becomes:

Observe

↓

Understand

↓

Generate Candidates

↓

Predict Outcomes

↓

Rank Decisions

↓

Choose

↓

Experiment

↓

Measure Result

↓

Update Knowledge 38. Updated M2.2.2 Architecture

After v0.4:

                    WORLD

                      ↓

             Evidence Foundation

                      ↓

            Cognitive Understanding

                      ↓

          Candidate Generation Engine

                      ↓

          Predictive Evaluation Layer

                      ↓

          Decision Ranking Engine

                      ↓

             Decision Record

                      ↓

          Experiment Framework

                      ↓

              Learning Memory

39. Implementation Boundary Update

M2.2.2 SHALL implement:

✅ Candidate models ✅ Decision scoring ✅ Candidate ranking ✅
Prediction interfaces ✅ Experiment records ✅ Learning records ✅
Simulation mode

M2.2.2 SHALL NOT implement:

❌ Real GPU modification ❌ Real pool switching ❌ Miner restart ❌
Automatic execution

40. Core Principle v0.4

MiningGuardian does not discover optimization by guessing.

It discovers opportunities through:

Evidence

-   

Prediction

-   

Controlled Validation

The agent behaves like an experienced mining engineer:

"I do not change the system because I can. I change it because evidence
shows the expected reward improvement is greater than the risk and
cost."

------------------------------------------------------------------------

ADR-0006 v0.5 MiningGuardian Decision Engine Specification Multi-Agent
Cognitive Architecture & Intelligence Boundary

Status: Draft v0.5 Milestone: M2.2.2 Purpose: Define the final cognitive
architecture, intelligence boundaries, and transition path from
reasoning to controlled execution.

41. Architectural Principle

MiningGuardian SHALL NOT be implemented as a single monolithic AI agent.

A single model responsible for:

hardware analysis blockchain analysis economic decisions execution

creates several risks:

reasoning conflicts poor explainability unsafe actions difficult
debugging

Therefore MiningGuardian adopts:

Specialized Cognitive Modules

Each module owns a specific intelligence domain.

42. Multi-Agent Cognitive Architecture

The system is divided into specialized intelligence layers:

                    MiningGuardian Core

                           |

        +------------------+------------------+

        |                  |                  |

Hardware Intelligence Mining Intelligence Economic Intelligence

        |                  |                  |

        +------------------+------------------+

                           |

                 Decision Intelligence Layer

                           |

                 Execution Authorization Layer

43. Hardware Intelligence Agent Purpose

Understand physical machine reality.

Responsibilities:

GPU health thermal behaviour power efficiency clock stability hardware
limitations

Inputs:

NVML Telemetry Historical GPU behaviour

Outputs:

Example:

{ "state":"thermal_margin_reduced",

"confidence":0.91,

"risk":

"medium" } It does NOT: change clocks change voltage control fans

It only provides intelligence.

44. Mining Intelligence Agent Purpose

Understand mining process performance.

Responsibilities:

effective hashrate accepted shares rejected shares stale shares miner
behaviour algorithm performance

Inputs:

SRBMiner API Mining logs Pool statistics

Outputs:

{ "performance_state":

"below_expected",

"cause_candidates":\[

"pool_latency",

"share_efficiency"

\] } 45. Network & Blockchain Intelligence Agent Purpose

Understand external mining environment.

Responsibilities:

network difficulty block reward block time algorithm conditions pool
behaviour reward probability

Outputs:

{ "network_condition":

"favorable",

"reward_opportunity":

0.07,

"confidence":

0.76 } 46. Economic Intelligence Agent Purpose

Convert technical conditions into economic value.

The question:

"Is this technically better, or actually more profitable?"

Evaluates:

reward per block block time difficulty energy cost opportunity cost

Output:

{ "expected_reward_change":

0.04,

"net_value":

0.02 } 47. Decision Intelligence Layer

This is the core of MiningGuardian.

It receives:

Hardware State

-   

Mining State

-   

Network State

-   

Economic State

Then performs:

Evidence Review

↓

Hypothesis Evaluation

↓

Candidate Ranking

↓

Decision Selection 48. LLM Integration Boundary

Important architectural decision:

LLM is NOT the Decision Engine.

The LLM is a reasoning assistant.

The LLM SHALL NOT directly receive:

raw telemetry streams GPU controls miner commands wallet information
execution permissions

The LLM receives:

Structured Cognitive Context:

{ "verified_evidence": \[\],

"active_hypotheses": \[\],

"candidate_actions": \[\],

"risk_constraints": \[\],

"historical_lessons": \[\] } 49. LLM Responsibilities

The LLM may help with:

Pattern interpretation

Example:

"These three signals historically indicate pool degradation."

Hypothesis generation

Example:

Possible causes:

Network degradation Pool instability Miner issue Explanation generation

Convert:

Decision Score = 0.72

into:

Human explanation.

50. LLM Limitations

The LLM SHALL NOT:

override safety rules invent missing evidence execute actions modify
hardware bypass confidence thresholds

The LLM proposes.

The Decision Engine validates.

51. Decision Authority Model

Decision ownership hierarchy:

Safety Layer

      ↓

Evidence Validation

      ↓

Decision Engine

      ↓

LLM Reasoning Support

      ↓

Execution Layer

Important rule:

Intelligence does not equal authority.

A smarter model does not automatically receive more permissions.

52. Decision Confidence Gate

Every decision must pass:

Evidence Quality

-   

Prediction Confidence

-   

Risk Evaluation

=

Decision Confidence

Example:

{ "decision":

"switch_pool",

"confidence":

0.82,

"allowed":

true }

Another:

{ "decision":

"increase_power",

"confidence":

0.41,

"allowed":

false } 53. Execution Permission Framework

Future execution requires three approvals:

1.  Technical Approval

Is it technically valid?

Example:

GPU has thermal margin.

2.  Economic Approval

Is expected reward improvement meaningful?

Example:

Gain \> transition cost.

3.  Safety Approval

Is risk acceptable?

Example:

No hardware danger.

Only:

Technical YES

AND

Economic YES

AND

Safety YES

creates:

EXECUTION_ALLOWED 54. Execution Levels

Future system actions are classified:

Level 0

Observation only

Current M2.2.2

READ ONLY Level 1

Recommendation

Example:

"Consider reducing power."

Human approval required.

Level 2

Controlled Experiment

Example:

Test profile for limited duration.

Level 3

Autonomous Optimization

Future milestone.

Requires:

proven models safety history confidence 55. Complete Cognitive
Architecture

Final architecture:

                REAL WORLD

                    ↓

             Data Collection Layer

                    ↓

             Evidence Foundation

                    ↓

        Specialized Intelligence Agents

     /             |              \

Hardware Mining Economic Agent Agent Agent

     \             |              /

              Decision Engine

                    ↓

          Candidate Evaluation

                    ↓

             Decision Ranking

                    ↓

            Decision Journal

                    ↓

          Learning Memory


                    ↓

          Future Control Layer

56. M2.2.2 Implementation Scope Build:

✅ Decision models ✅ Candidate generation ✅ Ranking engine ✅
Confidence engine ✅ Simulation framework ✅ Decision explanations ✅
Learning records

Do NOT build:

❌ LLM integration ❌ Real autonomous control ❌ Pool switching ❌ GPU
modification ❌ Miner restart automation

57. Final MiningGuardian Philosophy

MiningGuardian is not an AI that controls a miner.

It is an intelligence system that continuously answers:

"Given everything we know, what decision has the highest probability of
increasing sustainable mining reward without creating unacceptable
risk?"

The system earns authority through:

evidence prediction accuracy historical validation controlled learning

Not through model complexity.

------------------------------------------------------------------------

ADR-0006 v0.6 MiningGuardian Decision Engine Specification Decision
Lifecycle, State Machine & Persistence Architecture

Status: Draft v0.6 Milestone: M2.2.2 Purpose: Define the executable
architecture of the Decision Engine.

58. Decision Engine Architectural Position

The Decision Engine is positioned between:

Cognitive Understanding

and

Future Execution Layer

It does NOT control hardware.

Its responsibility is:

Convert validated knowledge into ranked, explainable, and measurable
decisions.

Complete flow:

WORLD STATE

      ↓

Evidence Foundation

      ↓

Cognitive Analysis

      ↓

Decision Engine

      ↓

Decision Record

      ↓

Learning Memory 59. Decision Lifecycle Model

Every decision follows a controlled lifecycle:

DETECTED

↓

ANALYZING

↓

PROPOSED

↓

VALIDATING

↓

APPROVED / REJECTED

↓

EXECUTED (Future)

↓

OBSERVED RESULT

↓

LEARNED 60. Decision State Definitions 60.1 DETECTED

A significant change has been identified.

Examples:

effective hashrate decrease reward opportunity detected thermal
behaviour changed

Input:

{ "event": "hashrate_degradation",

"confidence": 0.62 }

No decision exists yet.

60.2 ANALYZING

The system gathers:

evidence historical context possible causes

Output:

{ "hypotheses":\[ "pool_issue", "thermal_issue"\] } 60.3 PROPOSED

The system creates candidate decisions.

Example:

{ "candidate":

"evaluate_pool_change",

"expected_gain":

0.04 } 60.4 VALIDATING

The system checks:

Evidence

Do we have enough proof?

Economics

Is expected gain meaningful?

Safety

Is risk acceptable?

60.5 APPROVED

The decision passed all gates.

Example:

{ "decision":

"APPROVED",

"confidence":

0.87 }

Important:

Approved does NOT mean executed.

It means:

The decision is technically justified.

60.6 REJECTED

The engine records:

rejected option reason evidence

Example:

{ "decision":

"REJECTED",

"reason":

"Gain lower than switching cost" } 60.7 EXECUTED (Future)

Reserved for future control layer.

M2.2.2 does not execute.

60.8 LEARNED

After outcome measurement:

Compare:

Prediction:

Expected +5%

Reality:

Actual +2%

Store:

Prediction error 61. Decision Object Model

Core object:

DecisionRecord

Contains:

decision_id

timestamp

world_state_reference

evidence_ids

hypothesis_ids

candidate_actions

selected_action

confidence

risk_score

expected_gain

decision_state

explanation

outcome_reference 62. Candidate Action Schema

Every possible action:

CandidateAction

Structure:

{ "id": "candidate_001",

"type": "POOL_EVALUATION",

"expected_reward_gain": 0.05,

"confidence": 0.78,

"risk": 0.15,

"cost": 0.02,

"reversible": true,

"requires_execution": false } 63. Decision Scoring Storage

The engine stores not only the winner.

It stores all evaluated options.

Example:

{ "ranking":\[

{ "action": "stay_current",

"score": 0.72 },

{ "action": "switch_pool",

"score": 0.68 },

{ "action": "increase_power",

"score": 0.41 }

\] }

This is critical for future learning.

64. Database Architecture

M2.2.2 introduces new cognitive persistence.

Existing tables remain untouched.

New tables:

decision_candidates

Purpose:

Store generated possibilities.

Fields:

id

decision_id

action_type

expected_gain

risk

confidence

score

created_at decision_evaluations

Purpose:

Store ranking calculations.

Fields:

id

candidate_id

benefit_score

risk_score

uncertainty_score

final_score

model_version decision_outcomes

Purpose:

Compare prediction vs reality.

Fields:

id

decision_id

expected_result

actual_result

difference

lesson_generated

created_at 65. Integration With Existing M2.2.1

M2.2.2 consumes:

From Evidence Foundation:

EvidenceItem

Claim

Hypothesis

ReasoningResult

DecisionRecord

It does NOT replace them.

Relationship:

Evidence

↓

Hypothesis

↓

Decision Candidate

↓

Decision Evaluation

↓

Decision Record 66. Decision Engine API Boundary

The internal interface:

DecisionEngine.evaluate( context: AgentWorkingMemory )

Returns:

DecisionResult

Example:

{ "state":

"HOLD",

"selected_action":

"NONE",

"confidence":

0.91,

"explanation":

"Current configuration remains optimal" } 67. Decision Safety Gates

Every decision must pass:

Gate 1 --- Evidence Gate

Question:

Do we know enough?

Gate 2 --- Economic Gate

Question:

Is the expected reward improvement meaningful?

Gate 3 --- Risk Gate

Question:

Is the downside acceptable?

Gate 4 --- Continuity Gate

Question:

Does this threaten mining uptime?

Only:

PASS + PASS + PASS + PASS

creates:

APPROVED 68. Decision Explainability Requirement

Every decision MUST answer:

Why this decision?

Example:

Current pool degradation detected.

Alternative pool estimated +4.2% effective reward.

Switch cost estimated 1.8%.

Expected net improvement: +2.4%.

Confidence: 82%.

Decision: APPROVED FOR FUTURE EXECUTION. 69. Learning Architecture

Every completed decision creates:

Decision

↓

Prediction

↓

Outcome

↓

Error Analysis

↓

Knowledge Update

The system learns:

which predictions were accurate which assumptions failed which actions
were profitable which risks were underestimated 70. M2.2.2
Implementation Boundary Implement now:

✅ Decision models ✅ State machine ✅ Candidate generation interface ✅
Ranking engine ✅ Scoring engine ✅ Persistence ✅ Simulation mode ✅
Outcome tracking

Explicitly forbidden:

❌ GPU writes ❌ Clock changes ❌ Voltage changes ❌ Fan control ❌
Miner restart ❌ Pool switching ❌ Wallet changes

71. Final Architecture After v0.6 Mining Reality

                       ↓

              World State Builder

                       ↓

             Evidence Foundation

                       ↓

          Cognitive Interpretation Layer

                       ↓

          Candidate Generation Engine

                       ↓

          Prediction & Risk Analysis

                       ↓

          Decision Ranking Engine

                       ↓

             Decision State Machine

                       ↓

              Decision Journal

                       ↓

              Learning Memory


                       ↓

             Future Control Layer

72. Final Decision Philosophy

MiningGuardian follows:

"A decision is not valuable because it changes the system. A decision is
valuable because evidence proves that the expected improvement exceeds
its cost and risk."

The best agent is not the one that acts most frequently.

The best agent is the one that:

understands reality evaluates alternatives explains choices learns from
outcomes acts only when justified

------------------------------------------------------------------------

ADR-0006 v0.7 MiningGuardian Decision Engine Specification Production
Implementation Blueprint

Status: Draft v0.7 Milestone: M2.2.2 Purpose: Define the exact software
architecture, interfaces, data contracts, and implementation sequence of
the Decision Engine.

73. Implementation Philosophy

M2.2.2 implements the cognitive decision layer only.

It transforms:

Validated Context

into:

Ranked Decision Proposal

It does NOT:

execute commands control hardware modify miner configuration interact
with operating system processes 74. Final M2.2.2 Software Architecture

Target structure:

src/mining_guardian/

    agent/

        decision/

            __init__.py

            engine.py
            models.py
            scoring.py
            ranking.py
            confidence.py
            lifecycle.py
            candidates.py
            predictors.py
            policies.py

        cognition/

        records/

        memory/

    storage/

        decision_repository.py

75. Core Modules 75.1 decision/models.py

Purpose:

Define all Decision Engine data contracts.

CandidateAction

Represents a possible choice.

class CandidateAction: id: str

    action_type: ActionType

    expected_gain: float

    confidence: float

    risk_score: float

    transition_cost: float

    reversible: bool

    requires_execution: bool

DecisionScore

Stores ranking calculation.

class DecisionScore:

    benefit: float

    confidence_adjusted_value: float

    risk_penalty: float

    cost_penalty: float

    uncertainty_penalty: float

    final_score: float

DecisionResult

Final engine output.

class DecisionResult:

    decision_id: str

    state: DecisionState

    selected_action: CandidateAction

    alternatives: list[CandidateAction]

    confidence: float

    explanation: str

76. Decision Engine Interface

File:

decision/engine.py

Main interface:

class DecisionEngine:

    def evaluate(
        self,
        context: AgentWorkingMemory
    ) -> DecisionResult:
        ...

Internal flow:

AgentWorkingMemory

        ↓

Evidence Validation

        ↓

Candidate Generation

        ↓

Prediction

        ↓

Risk Evaluation

        ↓

Ranking

        ↓

Decision Result 77. Candidate Generation Module

File:

decision/candidates.py

Purpose:

Generate possible actions.

Interface:

class CandidateGenerator:

    def generate(
        context
    ) -> list[CandidateAction]:
        ...

Initial candidate sources:

Performance degradation

Example:

Hashrate below baseline

Generate:

Investigate cause Efficiency opportunity

Example:

TH/W declining

Generate:

Evaluate efficiency profile Network opportunity

Example:

Latency increased

Generate:

Evaluate pool condition 78. Prediction Module

File:

decision/predictors.py

Purpose:

Estimate future outcome.

Interface:

class OutcomePredictor:

    def predict(
        state,
        action
    ):
        ...

Output:

PredictionResult

Contains:

expected_reward_change

expected_hashrate_change

expected_power_change

confidence 79. Scoring Module

File:

decision/scoring.py

Implements:

$$ Score = (B \times C) - (R+A+U) $$

Interface:

class DecisionScorer:

    def score(
        candidate,
        prediction
    ):
        ...

80. Ranking Module

File:

decision/ranking.py

Purpose:

Order all available choices.

Interface:

class DecisionRanker:

    def rank(
        candidates
    ):
        ...

Rules:

Higher utility wins If scores are close:

Prefer:

Lower Risk

Higher Confidence

Lower Cost

More Reversible 81. Confidence Engine

File:

decision/confidence.py

Purpose:

Calculate decision trust level.

Formula:

$$ Confidence = EvidenceQuality \times Freshness \times PredictionReliability $$

Output:

ConfidenceScore 82. Decision Lifecycle State Machine

File:

decision/lifecycle.py

States:

class DecisionState:

    DETECTED

    ANALYZING

    PROPOSED

    VALIDATING

    APPROVED

    REJECTED

    OBSERVED

    LEARNED

Transitions:

DETECTED \| v ANALYZING \| v PROPOSED \| v VALIDATING

\| +---- REJECTED

\| v

APPROVED

\| v

OBSERVED

\| v

LEARNED 83. Decision Policies

File:

decision/policies.py

Purpose:

Store immutable safety rules.

Example:

class DecisionPolicy:

    minimum_confidence = 0.75

    minimum_gain = 0.03

    max_risk = 0.25

Rules:

No decision passes if:

Confidence \< threshold

OR

Risk \> allowed

OR

Expected gain \< transition cost 84. Persistence Layer

File:

storage/decision_repository.py

Stores:

Decision decision_id

timestamp

state

selected_action

confidence

score

explanation Candidate evaluations candidate_id

decision_id

score

ranking_position Outcomes prediction

actual_result

error

lesson 85. Database Migration

M2.2.2 adds:

decision_candidates

decision_scores

decision_outcomes

Existing tables:

UNCHANGED

86. CLI Additions

M2.2.2 should add read-only commands:

Inspect decision context mining-guardian decision-context

Shows:

current evidence hypotheses available candidates Run simulation
mining-guardian decision-simulate

Output:

Example:

Candidate ranking:

1.  HOLD Score: 0.82

2.  Pool evaluation Score: 0.65

3.  Power adjustment Score: 0.41 Explain decision mining-guardian
    decision-explain ID

4.  Testing Requirements

M2.2.2 MUST include:

Unit Tests Candidate generation

Test:

valid evidence creates candidates missing evidence creates none Scoring

Test:

higher reward improves score higher risk reduces score Ranking

Test:

safer option wins when scores are close Confidence

Test:

stale evidence lowers confidence Lifecycle

Test:

invalid transitions rejected Integration Tests

Test:

WorldState

↓

Evidence

↓

Decision Engine

↓

Decision Record 88. Simulation First Rule

Before any execution layer:

All decisions must run in:

SIMULATION MODE

The system must prove:

prediction accuracy decision quality false positive rate unnecessary
intervention rate 89. M2.2.2 Completion Criteria

M2.2.2 is complete when:

✅ Decision models implemented ✅ Candidate generation works ✅ Ranking
works ✅ Confidence works ✅ Persistence works ✅ Simulation works ✅
Tests pass

NOT required:

❌ Real execution ❌ GPU control ❌ Pool switching ❌ Miner restart

90. Final Architecture Statement

MiningGuardian Decision Engine is:

A risk-aware, evidence-driven decision system that evaluates possible
mining improvements, ranks alternatives, explains choices, and learns
from outcomes before any future execution authority is granted.

بعد v0.7

الآن أصبحت الوثيقة جاهزة كـ Codex Implementation Specification.

الانتقال الطبيعي بعد هذه النسخة:

M2.2.2 Execution Prompt Package

أي نحول ADR-0006 v0.7 إلى Prompt واحد لـCodex يحتوي:

الهدف القيود الملفات المطلوبة ترتيب التنفيذ الاختبارات المطلوبة ممنوعات
التنفيذ

وهذا سيكون أول Prompt فعلي لبناء Decision Engine داخل المشروع.

تمام , اجمع ADR-0006 - v0.1 - v0.2 - v0.3 - v0.4 - v0.5 - v0.6 - v0.7 في
ملف وثيقة واحد كامل و خرجه ك implementation specification للانتقال الى
M2.2.2 Execution Prompt Package

ممتاز. سأجمعها لك في وثيقة واحدة موحدة، لكن سأجري عليها عملية دمج هندسية
وليس مجرد نسخ ولصق.

الهدف سيكون إخراج:

ADR-0006 MiningGuardian Decision Engine Specification M2.2.2
Implementation Specification
