---
type: Reference
title: Initial Source Map
description: Records the project and format sources used to seed each curated concept.
tags: [references, provenance, okf]
timestamp: "2026-07-29T14:22:56Z"
---

# Initial Source Map

This reference records the live sources used to seed the MOX-ADV OKF bundle on 2026-07-29.
It preserves provenance without copying a stale raw snapshot into the bundle.

## Project Sources

| Source | Authority | Use |
| --- | --- | --- |
| [`requirements.md`](../../requirements.md) | Normative product and acceptance specification, version 2.7 | Product scope, architecture constraints, contracts, permissions, gates, tests, and evidence |
| [`AGENTS.md`](../../AGENTS.md) | Repository agent routing | Entry point for issue tracking, domain documentation, and OKF usage |
| [`docs/agents/domain.md`](../../docs/agents/domain.md) | Domain-documentation workflow | Routes future domain concepts to `CONTEXT.md` and accepted ADRs when they exist |
| [`docs/agents/issue-tracker.md`](../../docs/agents/issue-tracker.md) | Issue-tracker workflow | Defines GitHub Issues as the project planning surface |
| [`docs/agents/triage-labels.md`](../../docs/agents/triage-labels.md) | Triage vocabulary | Defines canonical issue states |

## Format Sources

| Source | Role |
| --- | --- |
| [Introducing the Open Knowledge Format](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing) | Explains the v0.1 living-wiki model, portability, producer and consumer independence, and progressive disclosure |
| [Pinned OKF v0.1 specification](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/ee67a5c/okf/SPEC.md) | Defines the exact format targeted by this bundle |
| [Current upstream OKF specification](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) | Tracks later format evolution; it is v0.2 as of 2026-07-29 and does not silently change this bundle's declared version |

## Concept Provenance

| OKF concept | Primary source locations |
| --- | --- |
| [Normative Specification](../project/normative-specification.md) | `requirements.md` sections 1, 17, 18, 20, and 21 |
| [Prototype Outcome and Scope](../product/prototype-outcome-and-scope.md) | `requirements.md` sections 2 and 3 |
| [Operating Modes and Human Authority](../product/operating-modes-and-human-authority.md) | `requirements.md` sections 4, 8.5, 8.6, 12, and 15 |
| [Closed Control Loop](../architecture/closed-control-loop.md) | `requirements.md` sections 2 and 5, `FR-MON-008`, `FR-MON-009`, and `FR-CTL-007` |
| [Trust and Write Boundaries](../architecture/trust-and-write-boundaries.md) | `requirements.md` sections 5, 6, 10, 12, and 14 |
| [Core Contracts and State](../implementation/core-contracts-and-state.md) | `requirements.md` sections 7, 8, 10, 12, 13, and 16 |
| [Delivery Gates and Evidence](../implementation/delivery-gates-and-evidence.md) | `requirements.md` sections 6.2, 13, and 17 through 21 |
| [External Write Safety](../runbooks/external-write-safety.md) | `requirements.md` `FR-CAM-003`, `FR-CAM-005` through `FR-CAM-007`, `FR-CTL-002` through `FR-CTL-006`, `FR-AUD-003`, and `NFR-005` |

The external documents named in Appendix A are review provenance and are not repository-local normative sources.
OKF concepts are derived orientation and are not authoritative inputs to acceptance.

# Citations

[1] [Introducing the Open Knowledge Format](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing)

[2] [Open Knowledge Format v0.1 specification, pinned at `ee67a5c`](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/ee67a5c/okf/SPEC.md)

[3] [Current Open Knowledge Format specification](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
