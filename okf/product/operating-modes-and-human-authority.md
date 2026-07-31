---
type: Operating Model
title: Operating Modes and Human Authority
description: Defines the three supported operating modes and the exact authority of the local human approver.
tags: [product, authority, approval]
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

# Operating Modes and Human Authority

The prototype supports three operating modes:[^requirements-v2]

- `OBSERVE` permits reading, validation, calculations, anomaly detection, and explanations without a write.
- `RECOMMEND` permits a typed proposal but cannot execute it.
- `APPROVAL_REQUIRED` permits at most one write for the exact proposal, target, diff, snapshot, policy version, expected fingerprint, and expiry confirmed by the operator.

The local application stores a single-use `Approval` bound to the canonical hash of the approved plan.
The executor accepts a `proposal_id`, loads the immutable proposal itself, and atomically marks the Approval as used.
Changing any bound field or allowing the Approval to expire requires a new proposal and confirmation.
The LLM cannot create or modify an Approval.

One local operator provides interactive confirmation.
Separate cryptographic human roles and long-lived Mandates are outside this prototype.
`BOUNDED_AUTONOMY` is explicitly outside scope, and every production write requires fresh human confirmation.
The developer owns technical preparation and operation, while the customer validates requirements and accepts the tested prototype.

[^requirements-v2]: [MOX-ADV prototype requirements](../../requirements-v2-prototype.md), `FR-006`, `FR-008`, responsibility, and acceptance capability rows.
