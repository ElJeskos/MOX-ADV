---
type: Decision Record
title: Gate 0 Record
description: Points consumers to the legacy Gate 0 record and the superseding read-only production boundary.
tags: [project, readiness, gate-0, safety]
timestamp: "2026-07-30T12:00:00Z"
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
  - id: modularization-amendment
    resource: "repository:requirements-modularization-v1.md"
    title: Normative modular product amendment
    last_modified: 2026-07-30
---

# Gate 0 Record

The legacy Gate 0 values and API matrix are recorded in `config/gate0-policy.json`.[^gate-0-policy]
The modularization amendment supersedes every legacy path that could authorize production write.[^modularization]
The record remains useful for inherited calculations, policy values, test semantics, and historical evidence.
Its pilot profiles and trusted-binding workflow grant no production authority.
Production is read-only at every gate.
Write-capable behavior is restricted to approved test compositions and test resources.
Issue #36 makes this normative boundary executable at the trusted seam; until then the existing `production_write_authorized = false` setting remains fail-closed.

[^gate-0-policy]: [MOX-ADV Gate 0 machine record](../../config/gate0-policy.json).
[^modularization]: [Normative modularization amendment](../../requirements-modularization-v1.md), version `1.0`.
