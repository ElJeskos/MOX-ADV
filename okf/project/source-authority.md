---
type: Source Authority
title: Source Authority
description: Defines which live sources govern MOX-ADV facts and how conflicts are resolved.
tags: [project, governance, provenance]
timestamp: "2026-07-30T12:00:00Z"
---

# Source Authority

The OKF bundle is the portable curated knowledge layer for MOX-ADV.
Facts governed by a live normative or executable source retain that source's authority.

Apply the following authority rules:

1. `requirements-modularization-v1.md` takes precedence over `requirements.md` version 2.7 and `requirements-v2-prototype.md` version 2.0-prototype only for product editions, customer integration, environment authority, evidence classification, and modular acceptance.
2. `requirements.md` version 2.7 remains the normative behavioral and acceptance baseline for every subject that the modularization amendment does not explicitly supersede.
3. Accepted ADRs record architectural decisions when they exist, while machine-readable schemas, implementation, tests, and runbooks must implement the normative contract without silently changing it.
4. At Gate 0, the live `api-matrix.yaml` becomes authoritative for verified API versions, endpoints, methods, object types, headers, and platform limits when the external Yandex contract has changed since the requirements were checked.
5. No API matrix, legacy credential profile, Approval, Mandate, or prior pilot decision may override the amendment's prohibition on production write.
6. `AGENTS.md` and `docs/agents/` govern agent workflow, not product behavior.
7. A derived OKF statement never overrides the live source from which it was synthesized.

When sources disagree, inspect the current source, surface the conflict explicitly, and update behavior only through the appropriate requirements or ADR decision.
Do not resolve a conflict by editing the OKF summary alone.

# Citations

[1] [Normative requirements](../../requirements.md)

[2] [Normative modularization amendment](../../requirements-modularization-v1.md)

[3] [Initial source map](../references/initial-source-map.md)
