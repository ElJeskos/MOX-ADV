---
type: Readiness Contract
title: Implementation Preconditions
description: Lists the decisions and evidence that must exist before implementation or any production write.
tags: [project, readiness, decisions, safety]
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

# Implementation Preconditions

The following decisions must be explicit before implementation or controlled production work can rely on them:[^requirements-v2]

1. Identify the primary business conversion and microconversions, including their identifiers, classification, and business meaning.
2. Choose one normative attribution model for snapshots.
3. Choose one supported campaign type and an applicable strategy.
4. Approve an API matrix containing object type, `v5` or `v501`, environment, host, path, service, method, and verification status.
5. Fix the pilot allowlist for account, campaign, counter, goal, and the single writer.
6. Choose one exact reversible controlled-pilot action and its readback.
7. Set the pilot monetary cap, loss threshold, and stop condition.
8. Set numeric freshness, watermark, and late-conversion cutoff values.
9. Set numeric polling intervals, anomaly thresholds, and the observation window.
10. Approve the fields exposed to the LLM and the retention period for artifacts.

Direct operation implementation must not begin until the supported campaign type and normative API matrix are fixed.
Any production write remains blocked until the remaining decisions are approved.
Fixture thresholds apply only to fixtures and sandbox verification unless the controlled-pilot policy separately approves production limits.

[^requirements-v2]: [MOX-ADV prototype requirements](../../requirements-v2-prototype.md), “Mandatory decisions before implementation.”
