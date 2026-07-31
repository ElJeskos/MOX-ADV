---
type: Migration Record
title: OKF v0.1 Migration
description: Records the audited v0.1 boundary and the deliberate v0.2 conversion decisions.
tags: [references, migration, provenance, okf]
generated:
  by: "codex/gpt-5"
  at: "2026-07-29T17:43:55Z"
verified:
  by: "codex/gpt-5"
  at: "2026-07-29T17:43:55Z"
status: stable
sources:
  - id: legacy-okf-v01
    resource: "git:281f329:okf/"
    title: Legacy MOX-ADV OKF v0.1 bundle
  - id: requirements-v2
    resource: "repository:requirements-v2-prototype.md"
    title: MOX-ADV prototype requirements version 2.0-prototype
    last_modified: 2026-07-29
  - id: okf-v02-spec
    resource: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/3fcbb9f/okf/SPEC.md
    title: Open Knowledge Format v0.2 specification
---

# OKF v0.1 Migration

The prior bundle at Git commit `281f329` declared OKF v0.1 and derived its product knowledge from the former `requirements.md` v2.7 baseline.[^legacy-okf-v01]
The mechanical migration audit found ten non-reserved concepts.
All ten used legacy `timestamp` metadata and `# Citations` sections, and all ten lacked v0.2 `generated`, `sources`, and `status` metadata.

The current bundle declares OKF v0.2.
Every retained concept uses structured provenance, real production metadata, lifecycle state, and claim-level footnotes where useful.[^okf-v02-spec]
The legacy source remains recoverable in Git history rather than being cloned into the new bundle.

Migration was not a mechanical field rename because the current requirements change the product boundary.[^requirements-v2]
The current bundle deliberately excludes the former `BOUNDED_AUTONOMY`, long-lived Mandate, cryptographic-role, and five-gate delivery claims.
The former `implementation/delivery-gates-and-evidence` concept was replaced by `implementation/acceptance-and-evidence`, which reflects the current fixture, scenario, capability, and evidence model.

No v0.1 fallback governs current behavior.
Historical material may be consulted for provenance only and must not override the current normative source.

[^legacy-okf-v01]: Legacy OKF v0.1 bundle preserved at Git commit `281f329`.
[^requirements-v2]: [MOX-ADV prototype requirements](../../requirements-v2-prototype.md), version `2.0-prototype`.
[^okf-v02-spec]: Open Knowledge Format v0.2 specification.
