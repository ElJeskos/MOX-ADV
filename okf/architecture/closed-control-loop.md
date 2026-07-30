---
type: System Architecture
title: Closed Control Loop
description: Describes the standalone module seam and the preserved paired flow from linked data through a test action to the post-change decision.
tags: [architecture, orchestration, feedback-loop]
timestamp: "2026-07-30T12:00:00Z"
---

# Closed Control Loop

MOX-ADV exposes one versioned deep module seam expressed as `ModuleRequestV1 -> ModuleResultV1`.
Standalone customer ecosystems call that seam through HTTP/JSON.
The paired runtime calls the same Metrika and Direct interfaces in process and retains one transactional state database and the existing Dashboard.
This design does not require microservices.

The paired logical flow remains:

`scheduler / CLI / internal API -> orchestrator -> LLM -> Proposal Store -> policy engine -> executor -> Yandex API`

The internal modules have distinct responsibilities:

- `monitoring` normalizes linked data, creates immutable snapshots, calculates metrics, and triggers analysis.
- `campaign_management` prepares campaign drafts, canonical diffs, and lifecycle transitions.
- `connectors` isolate typed read and write access to Direct, Metrica, and site publication.
- `decision` builds model context and validates structured model output.
- `policy` deterministically checks authority, scope, freshness, limits, cooldown, and kill-switch state.
- `execution` reserves an action, performs at most the authorized write, reads it back, and reconciles uncertainty.
- `audit` persists an immutable operational event sequence and evidence links.

Standalone Metrika does not import or configure Direct or Dashboard assets.
Standalone Direct does not import or configure Metrika or Dashboard assets.
The paired runtime owns cross-provider linking and orchestration without duplicating provider behavior.
Production traverses only the read, analysis, proposal, recommendation, and audit parts of the flow.
The executor may perform changing behavior only in approved test composition.

The loop does not end at a successful write.
A serving-impacting action opens an observation window, after which deterministic code creates an `ImpactReportV1`.
The orchestrator then starts a new analysis run and requires exactly one new immutable post-change `OptimizationProposalV1`.

MCP may adapt high-level commands to the orchestrator or internal API.
It is optional and is never the core contract, source of authority, or security boundary.

# Citations

[1] [`requirements-modularization-v1.md`](../../requirements-modularization-v1.md), product and integration contract matrices.

[2] [`requirements.md`](../../requirements.md), sections 2, 5, `FR-MON-008`, `FR-MON-009`, and `FR-CTL-007` for inherited paired behavior.

[3] [Core Contracts and State](../implementation/core-contracts-and-state.md)
