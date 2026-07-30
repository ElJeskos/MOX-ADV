---
type: Operating Model
title: Operating Modes and Human Authority
description: Explains the four operating modes and the human authority model for approvals, mandates, and incidents.
tags: [product, authority, governance]
timestamp: "2026-07-30T12:00:00Z"
---

# Operating Modes and Human Authority

The system has four persisted and audited operating modes:

- `OBSERVE` permits data collection, deterministic calculations, and explanation only.
- `RECOMMEND` may create a Proposal but cannot apply an Approval or Mandate.
- `APPROVAL_REQUIRED` permits a write only for the exact approved Proposal and canonical plan.
- `BOUNDED_AUTONOMY` permits the scheduler to execute only the action classes and scope explicitly granted by an active Mandate.

These mode semantics are inherited unchanged, but environment authority has priority over every mode.
In production, all four modes are read, analysis, recommendation, and Decision Record modes without write authority.
`APPROVAL_REQUIRED` and `BOUNDED_AUTONOMY` may exercise their existing write semantics only in an explicitly selected approved test contour.
Neither an Approval nor a Mandate can turn a production request into a write-capable request.

The developer holds three separate authenticated technical roles:

- The approver signs or revokes an exact Approval.
- The mandate issuer creates or revokes a bounded Mandate.
- The incident principal activates or clears the kill switch.

These roles use separate named principal IDs and signing keys even though one developer fills all three roles.
The customer validates requirements and performs final acceptance but does not issue operational authority.
The service principal and LLM never inherit a human role.

An Approval is single-use authority for one exact canonical plan and transaction.
A Mandate is immutable, revocable, time-bounded, quota-bounded, and limited to explicit targets and action classes.
The kill switch has priority over both and fails closed when its state is unavailable.

# Citations

[1] [`requirements.md`](../../requirements.md), sections 4, 8.5, 8.6, 12, and 15.

[2] [`requirements-modularization-v1.md`](../../requirements-modularization-v1.md), environment and credential matrix.

[3] [Trust and Write Boundaries](../architecture/trust-and-write-boundaries.md)
