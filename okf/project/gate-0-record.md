---
type: Decision Record
title: Gate 0 Record
description: Points consumers to the approved machine-readable Gate 0 decisions and their production-write boundary.
tags: [project, readiness, gate-0, safety]
timestamp: "2026-07-29T19:43:56Z"
generated:
  by: "codex/gpt-5"
  at: "2026-07-29T19:43:56Z"
verified:
  by: "codex/gpt-5"
  at: "2026-07-29T19:43:56Z"
status: stable
sources:
  - id: requirements-v2
    resource: "repository:requirements-v2-prototype.md"
    title: MOX-ADV prototype requirements version 2.0-prototype
    last_modified: 2026-07-29
  - id: gate-0-policy
    resource: "repository:config/gate0-policy.json"
    title: MOX-ADV Gate 0 machine record
    last_modified: 2026-07-29
---

# Gate 0 Record

The approved Gate 0 values and API matrix are recorded in `config/gate0-policy.json`.[^gate-0-policy]
The requirements remain the sole normative product source.[^requirements-v2]
The committed simulation profile is ready for implementation.
Production write remains blocked until an external trusted-binding manifest carries verified allowlist, ownership, provenance, readback, and unused `CreationReservation` evidence for every required binding.
This concept does not duplicate the policy values and grants no execution authority.

[^gate-0-policy]: [MOX-ADV Gate 0 machine record](../../config/gate0-policy.json).
[^requirements-v2]: [MOX-ADV prototype requirements](../../requirements-v2-prototype.md), version `2.0-prototype`.
