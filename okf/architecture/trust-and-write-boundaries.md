---
type: Safety Boundary
title: Trust and Write Boundaries
description: Defines the data, credential, target, network, and write boundaries that fail closed around the executor.
tags: [architecture, security, trust-boundary]
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

# Trust and Write Boundaries

The LLM has no OAuth token, arbitrary endpoint, credential profile, unrestricted target identifier, raw API response, arbitrary HTTP payload, or direct write capability.
The executor resolves targets and credentials from trusted configuration and is the only component that receives the pilot credential immediately before an allowed request.[^requirements-v2]

Direct production read, Direct sandbox write, Metrica test write, test-site publication, and Direct pilot write use separate logical profiles and credentials.
The read-only process has no write credential.
The pilot profile is disabled by default and is limited to one allowlisted campaign, one action, and the approved platform-side spend cap.

Network access is limited to the endpoints in the approved API matrix, the required Metrica endpoints, `mc.yandex.ru`, and one model provider over HTTPS port 443.
Redirects and production-delete operations are prohibited.
Unknown endpoint and API combinations fail before a network request.

URLs, UTM values, search terms, DOM content, and API errors are untrusted and must be redacted before model use.
Write-capable OAuth tokens remain in macOS Keychain.
The local production read-only dashboard may read only its Direct and Metrika tokens from a repository-root `.env` file owned by the current user with mode `0600` or stricter `0400`.
OAuth tokens must not enter prompts, process environment variables, command-line arguments, Docker metadata, code, standard output, exceptions, or artifacts.

Before a write, deterministic checks bind the allowlisted scope, exact proposal and diff, current fingerprint, fresh comparable snapshot, sample sufficiency, numerical limits, pilot cap, unused execution key, and single-writer condition.
A timeout triggers readback rather than a blind retry.
An unknown result blocks the next write until manual verification.

A timeout or lost response never permits a blind write retry.
Readback and reconciliation classify the observed state as applied, failed, or unknown.
An unknown result blocks further actions until human reconciliation.

[^requirements-v2]: [MOX-ADV prototype requirements](../../requirements-v2-prototype.md), `FR-004`, `FR-005`, `FR-008`, `NFR-003`, and `NFR-004`.
