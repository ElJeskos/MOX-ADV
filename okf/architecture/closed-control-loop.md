---
type: System Architecture
title: Closed Control Loop
description: Describes the monitored recommendation-and-write loop and the separation between model judgment and deterministic control.
tags: [architecture, orchestration, feedback-loop]
generated:
  by: "codex/gpt-5"
  at: "2026-07-29T17:43:55Z"
verified:
  by: "codex/gpt-5"
  at: "2026-07-29T17:43:55Z"
status: stable
sources:
  - id: requirements-v2
    resource: "repository:requirements-v2-prototype.md"
    title: MOX-ADV prototype requirements version 2.0-prototype
    last_modified: 2026-07-29
---

# Closed Control Loop

The loop begins with an `IntegratedPerformanceSnapshot` that joins allowlisted Direct and Metrica facts for one campaign, goal, and calendar-day grain.
Deterministic validation establishes provenance, freshness, comparability, calculations, scope, and sample sufficiency before any model analysis.[^requirements-v2]

The LLM receives only a normalized projection, the business goal, permitted change history, and policy limits.
It returns a typed `OptimizationProposalV1` containing observed facts, ranked hypotheses, evidence references, bounded actions, expected direction, risks, preconditions, and rollback conditions.
The deterministic policy layer independently checks the proposal and computes technical target values.

An action can pass to the executor only in `APPROVAL_REQUIRED` mode with exact human confirmation and a matching current fingerprint.
The executor reserves the execution key, performs no more than one write, reads the object back, and reconciles uncertainty without a blind retry.

A successful pilot write produces a new snapshot after the observation window and an `impact_report.json`.
The report may inform a later LLM recommendation, but every later action requires a new proposal and a new confirmation.
Without a pre-approved experimental design, the observed result is not described as causal impact.

The loop does not end at a successful write.
A serving-impacting action opens an observation window, after which deterministic code creates an `ImpactReportV1`.
The orchestrator then starts a new analysis run and requires exactly one new immutable post-change `OptimizationProposalV1`.

MCP may adapt high-level commands to the orchestrator or internal API.
It is optional and is never the core contract, source of authority, or security boundary.

[^requirements-v2]: [MOX-ADV prototype requirements](../../requirements-v2-prototype.md), goal, `FR-001`, `FR-005` through `FR-009`, and `NFR-004`.
