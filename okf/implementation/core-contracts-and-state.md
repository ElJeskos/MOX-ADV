---
type: Implementation Contract
title: Core Contracts and State
description: Summarizes the versioned schemas, immutable records, authority state machines, and execution ledger.
tags: [implementation, contracts, state]
timestamp: "2026-07-29T14:10:28Z"
---

# Core Contracts and State

Every model-visible and persisted contract is versioned and closed to unknown fields.
Machine-readable JSON Schemas in `schemas/` must match the normative model definitions in `requirements.md`; the requirements win until an approved new version changes them.
Identifiers, timestamps, money, limits, and evidence references are validated outside the LLM.

The central immutable records are:

- `IntegratedPerformanceSnapshotV1`, which joins source provenance, configuration, object state, metrics, data quality, comparability, confidence, and baseline.
- `OptimizationProposalV1`, which contains one typed decision, evidence references, bounded atomic actions, risks, preconditions, and an explanation.
- `ImpactReportV1`, which contains only deterministically calculated post-change facts and never contains the next decision.

Canonical JSON and SHA-256 bind snapshots, proposals, plans, fingerprints, reservations, and execution keys to exact versions of their inputs.
Money is stored as integer microrubles.
Policy comparisons use unrounded values.

Write authority and recovery are durable state machines:

- `ApprovalV1` is reserved atomically before the first write, becomes `USED_IN_SAGA` at the first HTTP-send boundary, and can authorize only remaining steps of the same unchanged canonical plan until the saga expires or terminates.
- `MandateV1` is immutable and consumes action and monetary quotas atomically.
- `ExecutionLedger` has a unique `execution_key`, records `IN_FLIGHT` before the external request, prevents duplicate application, and preserves uncertain or partially applied outcomes.
- `CreationReservationV1` binds not-yet-created objects to trusted scope and registers created IDs into the ledger.
- Kill-switch state, active observation windows, authority state, and unfinished sagas must recover after restart.

Every model-visible tool returns exactly one typed result, including denials, timeouts, and internal errors.
Side-effecting tool requests must become persisted Proposals before the executor can consider them.

# Citations

[1] [`requirements.md`](../../requirements.md), sections 7, 8, 10, 12, 13, and 16.

[2] [Trust and Write Boundaries](../architecture/trust-and-write-boundaries.md)
