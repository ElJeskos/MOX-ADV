---
type: System Architecture
title: Closed Control Loop
description: Describes the modular system flow from linked data through execution to the post-change decision.
tags: [architecture, orchestration, feedback-loop]
timestamp: "2026-07-29T14:10:28Z"
---

# Closed Control Loop

MOX-ADV is a modular application with one transactional state database, not a microservice system.
Its logical flow is:

`scheduler / CLI / internal API -> orchestrator -> LLM -> Proposal Store -> policy engine -> executor -> Yandex API`

The internal modules have distinct responsibilities:

- `monitoring` normalizes linked data, creates immutable snapshots, calculates metrics, and triggers analysis.
- `campaign_management` prepares campaign drafts, canonical diffs, and lifecycle transitions.
- `connectors` isolate typed read and write access to Direct, Metrica, and site publication.
- `decision` builds model context and validates structured model output.
- `policy` deterministically checks authority, scope, freshness, limits, cooldown, and kill-switch state.
- `execution` reserves an action, performs at most the authorized write, reads it back, and reconciles uncertainty.
- `audit` persists an immutable operational event sequence and evidence links.

The loop does not end at a successful write.
A serving-impacting action opens an observation window, after which deterministic code creates an `ImpactReportV1`.
The orchestrator then starts a new analysis run and requires exactly one new immutable post-change `OptimizationProposalV1`.

MCP may adapt high-level commands to the orchestrator or internal API.
It is optional and is never the core contract, source of authority, or security boundary.

# Citations

[1] [`requirements-v2-prototype.md`](../../requirements-v2-prototype.md)

[2] [Core Contracts and State](../implementation/core-contracts-and-state.md)
