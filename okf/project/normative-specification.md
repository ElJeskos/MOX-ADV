---
type: Project Contract
title: Normative Specification
description: Identifies the normative requirements baseline, readiness gates, and acceptance authority.
tags: [project, requirements, acceptance]
timestamp: "2026-07-29T14:22:56Z"
---

# Normative Specification

The repository currently describes a pre-implementation prototype through `requirements.md` version 2.7, dated 2026-07-29.
That document is the final unified specification intended for customer validation before Gates 1 through 4.
Its sections 1 through 22 are normative.
Appendix A is provenance and review traceability, not a second source of requirements.

The specification makes readiness evidence part of the contract:

- The unified Gate 0 must close before Gate 1, evidentiary Direct API integration, or any external write begins.
- Acceptance is determined by the capability matrix and atomic acceptance cases.
- The result is `PROVEN` only when every mandatory capability is proven and the complete closed-loop scenario succeeds on one allowlisted campaign.

An OKF concept may summarize these rules but must not introduce a new acceptance criterion, parameter value, permission, or exception.

# Citations

[1] [`requirements.md`](../../requirements.md), sections 1, 17, 18, 20, and 21.

[2] [Source Authority](source-authority.md)
