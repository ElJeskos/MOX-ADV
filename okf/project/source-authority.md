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

1. `requirements-v2-prototype.md` version `2.0-prototype` is the sole normative product and acceptance specification for this prototype.
2. `requirements.md` version 2.7 and OKF material derived from it are stale superseded artifacts and must not expand scope or alter implementation.
3. Accepted ADRs record architectural decisions when they exist, while machine-readable schemas, implementation, tests, and runbooks must implement the normative contract without silently changing it.
4. `AGENTS.md` and `docs/agents/` govern agent workflow, not product behavior.
5. A derived OKF statement never overrides the live source from which it was synthesized.

When sources disagree, inspect the current source, surface the conflict explicitly, and update behavior only through the appropriate requirements or ADR decision.
Do not resolve a conflict by editing the OKF summary alone.

# Citations

[1] [Normative prototype requirements](../../requirements-v2-prototype.md)

[2] [Initial source map](../references/initial-source-map.md)
