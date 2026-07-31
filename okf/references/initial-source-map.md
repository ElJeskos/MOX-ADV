---
type: Reference
title: Initial Source Map
description: Maps authoritative repository sources, format sources, and migration provenance to the curated MOX-ADV concepts.
tags: [references, provenance, okf]
generated:
  by: "codex/gpt-5"
  at: "2026-07-30T13:53:15Z"
verified:
  by: "codex/gpt-5"
  at: "2026-07-30T13:53:15Z"
status: stable
sources:
  - id: requirements-v2
    resource: "repository:requirements-v2-prototype.md"
    title: MOX-ADV prototype requirements version 2.0-prototype
    last_modified: 2026-07-30
  - id: agents
    resource: "repository:AGENTS.md"
    title: Repository agent routing
  - id: domain-workflow
    resource: "repository:docs/agents/domain.md"
    title: Domain documentation workflow
  - id: issue-workflow
    resource: "repository:docs/agents/issue-tracker.md"
    title: GitHub issue workflow
  - id: triage-workflow
    resource: "repository:docs/agents/triage-labels.md"
    title: Triage label vocabulary
  - id: okf-v02-spec
    resource: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/3fcbb9f/okf/SPEC.md
    title: Open Knowledge Format v0.2 specification
  - id: legacy-okf-v01
    resource: "git:281f329:okf/"
    title: Legacy MOX-ADV OKF v0.1 bundle
---

# Initial Source Map

This concept records live provenance without copying a stale raw source layer into the bundle.
Its structure follows the pinned OKF v0.2 specification.[^okf-v02-spec]

## Project Sources

| Source ID | Authority role | Derived concepts |
| --- | --- | --- |
| `requirements-v2` | Current product and acceptance specification, including Dashboard campaign goals and responsive ads, navigation, decision-journal, and linked-outcome behavior | Every project, product, architecture, implementation, and runbook concept |
| `agents` | Repository agent routing only | The repository adapter path |
| `domain-workflow` | Domain-documentation workflow only | Future `CONTEXT.md` and ADR routing |
| `issue-workflow` | GitHub issue workflow only | No product behavior |
| `triage-workflow` | Canonical issue-state vocabulary only | No product behavior |

## Format and Migration Sources

| Source ID | Role |
| --- | --- |
| `okf-v02-spec` | Defines the portable OKF v0.2 format and metadata semantics |
| `legacy-okf-v01` | Preserves migration provenance in Git history and is not authority for current product behavior |

The legacy bundle described the deleted `requirements.md` v2.7 baseline and included bounded-autonomy, Mandate, and delivery-gate claims that conflict with the current prototype boundary.
Those claims were not carried into current concepts.[^legacy-okf-v01]

[^okf-v02-spec]: Open Knowledge Format v0.2 specification
[^legacy-okf-v01]: Legacy OKF v0.1 bundle preserved at Git commit `281f329`.
