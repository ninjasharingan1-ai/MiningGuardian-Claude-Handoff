# ADR 0005 M2.2.1 Cognitive Evidence Foundation

## Problem
Future reasoning requires auditable structured knowledge.

## Context
MiningGuardian must separate observations, evidence, claims, hypotheses, and decisions.

## Architecture
Added pure Pydantic cognitive contracts. No persistence or model provider.

## Decisions
Evidence preserves provenance. Validation is deterministic. Records preserve traceability.

## Alternatives rejected
No LLM integration, vector database, or autonomous control.

## Safety
No execution capability added.

## Validation
Runtime tests and quality gates must verify serialization and validation behavior.

## Limitations
No real reasoning model exists yet.

## Reconsideration triggers
Introduce later only when measured requirements justify it.
