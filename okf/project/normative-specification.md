---
type: Project Contract
title: Normative Specification
description: Identifies the normative behavioral baseline, modular amendment, readiness gates, and acceptance authority.
tags: [project, requirements, acceptance]
timestamp: "2026-07-30T12:00:00Z"
---

# Normative Specification

The repository preserves its behavioral baseline in `requirements.md` version 2.7, dated 2026-07-29.
The approved `requirements-modularization-v1.md` amendment, dated 2026-07-30, supersedes that baseline only for product editions, customer integration, environment authority, evidence classification, and modular acceptance.
The amendment defines headless standalone Metrika, headless standalone Direct, and the paired product with the existing Dashboard.
It also makes production read-only and confines every changing scenario to an approved test contour.
All calculations, policy decisions, execution and reconciliation semantics, Decision Records, audit behavior, and paired behavior remain inherited from version 2.7.
Appendix A in the baseline is provenance and review traceability, not a second source of requirements.

The specification makes readiness evidence part of the contract:

- The unified Gate 0 must close before Gate 1 or any external integration evidence begins.
- Production write is forbidden at every gate.
- Acceptance is determined by the edition-applicable capability matrix and atomic acceptance cases.
- Write-capable acceptance evidence must come from an explicit test contour.
- The paired result is `PROVEN` only when every paired mandatory capability and the complete test-contour closed loop succeed without changing current Dashboard behavior.

An OKF concept may summarize these rules but must not introduce a new acceptance criterion, parameter value, permission, or exception.

# Citations

[1] [`requirements.md`](../../requirements.md), sections 1, 17, 18, 20, and 21.

[2] [`requirements-modularization-v1.md`](../../requirements-modularization-v1.md).

[3] [Source Authority](source-authority.md)
