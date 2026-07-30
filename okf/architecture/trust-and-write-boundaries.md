---
type: Safety Boundary
title: Trust and Write Boundaries
description: Defines where model output ends and deterministic write authority begins.
tags: [architecture, security, trust-boundary]
timestamp: "2026-07-29T14:10:28Z"
---

# Trust and Write Boundaries

The LLM produces typed analysis and proposals but has no write authority.
It must not receive OAuth tokens, arbitrary target IDs, endpoints, credential profiles, Approval objects, Mandates, or arbitrary HTTP payloads.
Trusted target IDs, credentials, authority objects, and execution keys are resolved server-side from the run context.

The policy engine is deterministic and cannot be bypassed by model output, prompt text, or a client payload.
The executor is the only component allowed to call changing APIs.
Every write is constrained by a server-side allowlist, a dedicated least-privilege credential profile, current object state, and either an applicable Approval or Mandate.

All text originating in APIs, ads, UTM values, site DOM, and business briefs is untrusted data.
It cannot alter instructions, available tools, scope, authority, or policy.
Secrets and direct identifiers stay outside model context, logs, artifacts, environment variables, command-line arguments, and persistent configuration.

Immediately before each external write, the executor must fail closed unless all applicable checks succeed:

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

[1] [`requirements-v2-prototype.md`](../../requirements-v2-prototype.md)

[2] [External Write Safety](../runbooks/external-write-safety.md)
