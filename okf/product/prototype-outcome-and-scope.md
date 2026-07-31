---
type: Product Scope
title: Prototype Outcome and Scope
description: Defines the controlled-loop proof goal, narrow pilot boundary, and explicit prototype non-goals.
tags: [product, scope, pilot]
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

# Prototype Outcome and Scope

MOX-ADV must prove one controlled loop:

`linked Direct and Metrica data -> metrics -> LLM analysis -> proposal -> policy check -> human confirmation -> change -> readback -> observed result`

The monitoring module reads one campaign and one counter, joins their data, calculates metrics, detects problems, and produces an explainable recommendation.
The safe campaign-management module prepares a campaign structure and may execute one bounded action only after explicit operator confirmation.[^requirements-v2]

The prototype is limited to one local operator, one test account, one allowlisted advertising account, one allowlisted pilot campaign, one supported campaign type, one counter, one primary goal, and one separate candidate test goal.
It includes local fixtures, available real-statistics reads, a confirmed campaign-creation lifecycle in the test contour, scheduled and one-off read-only analysis, one manually approved reversible pilot action, readback, an observed-result report, a CLI, and local artifacts.

The prototype does not include multiple clients or campaign types, autonomous production writes, long-lived Mandates, production-site or existing production-goal changes, automatic production deletion, generated media, a web interface, CRM or offline conversions, paid hosting, cloud deployment, microservices, high availability, or proof of causal KPI uplift.
It proves measurement correctness and execution safety rather than guaranteed business improvement.

[^requirements-v2]: [MOX-ADV prototype requirements](../../requirements-v2-prototype.md), “Goal,” “Scope,” and `FR-007`.
