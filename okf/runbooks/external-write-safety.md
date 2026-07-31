---
type: Runbook
title: External Write Safety
description: Routes an operator through approval, execution, readback, and uncertainty handling for the single pilot write.
tags: [runbook, safety, external-write]
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

# External Write Safety

This checklist routes the one controlled-pilot write.
It summarizes the normative requirements but does not grant authority.[^requirements-v2]

## Before approval

1. Confirm that every mandatory pre-implementation and production-write decision is approved.
2. Confirm `APPROVAL_REQUIRED` mode and `automation_enabled`.
3. Resolve the exact allowlisted account, campaign, counter, goal, endpoint, API version, service, method, credential profile, and single writer from trusted configuration.
4. Load the immutable proposal and show the operator the target, current and proposed values, exact diff, risk, rollback condition, and expiry.
5. Verify schema validity, evidence references, scope, freshness, comparability, sample sufficiency, expected fingerprint, numerical limits, pilot cap, absence of another write, and an unused execution key.
6. Persist a single-use Approval for the exact canonical plan.

## At the write boundary

1. Atomically reserve the execution key and transition the ledger to `IN_FLIGHT` before sending the request.
2. Let the executor load the proposal and trusted target itself, consume the exact Approval, and obtain the pilot credential only for the allowed request.
3. Reject redirects, unknown API-matrix combinations, changed fingerprints, expired approvals, out-of-bounds values, foreign targets, and production deletes before the write.
4. Send no more than one write in the run.

## After the request

1. Validate the HTTP result, object-level errors, warnings, and actual returned object type.
2. Read the object back and compare it with the exact expected state.
3. Record `APPLIED` for the target state, `NO_CHANGE` when it was already present, or `FAILED` when the original state is confirmed after timeout.
4. Record `UNKNOWN_RESULT` when state cannot be determined, and block every later write until manual reconciliation.
5. Never retry a write blindly after timeout or a lost response.
6. After a serving change, wait for the approved observation window, create a new snapshot and impact report, and require a new proposal and confirmation for any next action.

After the final prototype decision, disable production write and revoke or remove the prototype OAuth tokens as required by the normative source.

[^requirements-v2]: [MOX-ADV prototype requirements](../../requirements-v2-prototype.md), mandatory decisions, `FR-008`, `FR-009`, `NFR-003`, `NFR-004`, and final acceptance conditions.
