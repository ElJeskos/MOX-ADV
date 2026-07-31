---
type: Source Authority
title: Source Authority
description: Defines the authority order for product requirements, verified API facts, executable behavior, and agent workflow.
tags: [project, governance, provenance]
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
  - id: source-map
    resource: /references/initial-source-map.md
    title: Initial Source Map
---

# Source Authority

The OKF bundle is the portable curated knowledge layer for MOX-ADV.
It is derived orientation and does not grant product, operational, or write authority.

Apply this authority order:

1. `requirements-v2-prototype.md` version `2.0-prototype` is the current repository-local product and acceptance specification.[^requirements-v2]
2. An approved `api-matrix.yaml`, when created, governs the verified Yandex API version, environment, host, path, service, method, object type, and verification status for integration work.
3. Accepted ADRs govern architectural decisions when they exist, while executable schemas, implementation, tests, and runbooks must conform to the normative product contract without silently changing it.
4. `AGENTS.md` and `docs/agents/` govern agent workflow and repository integration, not product behavior.
5. Derived OKF concepts never override the current live source from which they were synthesized.[^source-map]

When sources disagree, inspect the current sources, surface the conflict, and resolve it through the applicable requirements or ADR process.
Update the authoritative source before updating its derived concepts.

[^requirements-v2]: [MOX-ADV prototype requirements](../../requirements-v2-prototype.md), version `2.0-prototype`, dated 2026-07-29.
[^source-map]: [Initial Source Map](../references/initial-source-map.md).
