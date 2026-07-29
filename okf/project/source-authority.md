---
type: Source Authority
title: Source Authority
description: Defines which live sources govern MOX-ADV facts and how conflicts are resolved.
tags: [project, governance, provenance]
timestamp: "2026-07-29T14:22:56Z"
---

# Source Authority

The OKF bundle is the portable curated knowledge layer for MOX-ADV.
Facts governed by a live normative or executable source retain that source's authority.

Apply the following authority rules:

1. `requirements.md` version 2.7 is the normative product and acceptance specification until an approved revision supersedes it.
2. Accepted ADRs record architectural decisions when they exist, while machine-readable schemas, implementation, tests, and runbooks must implement the normative contract without silently changing it.
3. At Gate 0, the live `api-matrix.yaml` becomes authoritative for verified API versions, endpoints, methods, object types, headers, and platform limits when the external Yandex contract has changed since the requirements were checked.
4. `AGENTS.md` and `docs/agents/` govern agent workflow, not product behavior.
5. A derived OKF statement never overrides the live source from which it was synthesized.

When sources disagree, inspect the current source, surface the conflict explicitly, and update behavior only through the appropriate requirements or ADR decision.
Do not resolve a conflict by editing the OKF summary alone.

# Citations

[1] [Normative requirements](../../requirements.md)

[2] [Initial source map](../references/initial-source-map.md)
