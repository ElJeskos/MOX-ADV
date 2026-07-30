---
type: Operating Model
title: Operating Modes and Human Authority
description: Explains the four operating modes and the human authority model for approvals, mandates, and incidents.
tags: [product, authority, governance]
timestamp: "2026-07-29T14:10:28Z"
---

# Operating Modes and Human Authority

The system has four persisted and audited operating modes:

- `OBSERVE` permits data collection, deterministic calculations, and explanation only.
- `RECOMMEND` may create a Proposal but cannot apply an Approval or Mandate.
- `APPROVAL_REQUIRED` permits a write only for the exact approved Proposal and canonical plan.
- `BOUNDED_AUTONOMY` permits the scheduler to execute only the action classes and scope explicitly granted by an active Mandate.

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

[1] [`requirements-v2-prototype.md`](../../requirements-v2-prototype.md)

[2] [Trust and Write Boundaries](../architecture/trust-and-write-boundaries.md)
