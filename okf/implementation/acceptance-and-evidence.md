---
type: Acceptance Model
title: Acceptance and Evidence
description: Summarizes fixture, scenario, capability-status, and evidence requirements for prototype acceptance.
tags: [implementation, acceptance, testing, evidence]
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

# Acceptance and Evidence

Eight named fixtures verify deterministic calculations and policy paths without imposing a single deterministic LLM answer:

- `BUDGET_INCREASE_ON`
- `BUDGET_DECREASE_ON`
- `BID_INCREASE_ON`
- `BID_DECREASE_ON`
- `LOW_CTR_ON`
- `NO_CONVERSION_ON`
- `EFFECTIVE_SUSPENDED`
- `INSUFFICIENT_ON`

Their exact inputs and expected budget, bid, variant, suspend, resume, or no-write results remain normative in the requirements.[^requirements-v2]
Model quality is separately tested through repeated schema-valid, evidence-grounded responses that request human judgment or more data when input is ambiguous.

The sixteen acceptance scenarios cover the API matrix, Direct method coverage, the Metrica test event, fixture calculations, invalid-input blocking, linked real data, incompatibility, repeated LLM analysis, campaign and goal lifecycles, mode enforcement, the single pilot action, adversarial safety cases, timeout reconciliation, scheduled monitoring, impact reporting, local runtime constraints, cost limits, cleanup, Keychain access, and secret exclusion.

Each capability receives `PROVEN`, `NOT_PROVEN`, `INCONCLUSIVE`, or `NOT_TESTED` together with an evidence class of `SANDBOX`, `TEST_COUNTER`, `REAL_READ_ONLY`, `SIMULATED`, or `CONTROLLED_PILOT`.
Every mandatory capability must be `PROVEN` for the overall result to be `PROVEN`.
A mandatory `NOT_PROVEN` makes the overall result `NOT_PROVEN`; otherwise a mandatory `INCONCLUSIVE` makes it `INCONCLUSIVE`.

`BOUNDED_AUTONOMY`, production campaign creation, production-site publication, and production goal lifecycle are outside the current acceptance scope and cannot be claimed as proven by this prototype.
Sandbox evidence cannot prove production-write capability, and separate read-only and sandbox-write evidence cannot prove the closed loop.
Positive KPI growth is not an acceptance condition.

[^requirements-v2]: [MOX-ADV prototype requirements](../../requirements-v2-prototype.md), “Acceptance Conditions,” including the fixture, scenario, capability, and evidence tables.
