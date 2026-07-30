---
type: Safety Boundary
title: Trust and Write Boundaries
description: Defines model, customer-contract, environment, credential, and deterministic test-write boundaries.
tags: [architecture, security, trust-boundary]
timestamp: "2026-07-30T12:00:00Z"
---

# Trust and Write Boundaries

The LLM produces typed analysis and proposals but has no write authority.
It must not receive OAuth tokens, arbitrary target IDs, endpoints, credential profiles, Approval objects, Mandates, or arbitrary HTTP payloads.
Trusted target IDs, credentials, authority objects, and execution keys are resolved server-side from the run context.

The policy engine is deterministic and cannot be bypassed by model output, prompt text, or a client payload.
The executor is the only component allowed to call changing APIs.
Every write is constrained by a server-side allowlist, a dedicated least-privilege credential profile, current object state, and either an applicable Approval or Mandate.

Environment authorization is checked before those existing write checks.
Production compositions expose only `DIRECT_PROD_READ` and `METRIKA_PROD_READ`.
Every production write request is rejected before resolving a write credential and before network egress.
Approval, Mandate, mode, retry, restart, customer evidence, and adapter selection cannot weaken that restriction.
Write profiles are available only to explicitly selected test compositions and explicit test resources.

Customer requests reference stored connections.
They cannot carry raw OAuth tokens, arbitrary endpoints, arbitrary provider payloads, trusted target IDs, or write credentials.
Standalone modules return typed results and Decision Record references without exposing the trusted execution boundary.

All text originating in APIs, ads, UTM values, site DOM, and business briefs is untrusted data.
It cannot alter instructions, available tools, scope, authority, or policy.
Secrets and direct identifiers stay outside model context, logs, artifacts, environment variables, command-line arguments, and persistent configuration.

After the environment is confirmed as test and immediately before each external write, the executor must fail closed unless all applicable checks succeed:

- Endpoint, service, API version, credential profile, organization, account, target, and action are allowlisted.
- Snapshot or current-state evidence is fresh and compatible for the current transition.
- Expected canonical fingerprint, cooldown, quotas, monetary limits, and campaign serialization hold.
- Approval or Mandate scope and lifecycle state remain valid.
- The kill switch is available and inactive for the applicable scope.
- The audit event and execution reservation can be persisted transactionally.

A timeout or lost response never permits a blind write retry.
Readback and reconciliation classify the observed state as applied, failed, or unknown.
An unknown result blocks further actions until human reconciliation.

# Citations

[1] [`requirements-modularization-v1.md`](../../requirements-modularization-v1.md), integration contract and environment matrices.

[2] [`requirements.md`](../../requirements.md), sections 5, 6, `FR-CAM-005` through `FR-CAM-007`, `FR-CTL-002` through `FR-CTL-005`, and `NFR-002` through `NFR-005` for inherited test-write behavior.

[3] [External Write Safety](../runbooks/external-write-safety.md)
