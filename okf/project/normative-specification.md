---
type: Project Contract
title: Normative Specification
description: Identifies the normative requirements baseline, readiness gates, and acceptance authority.
tags: [project, requirements, acceptance]
timestamp: "2026-07-29T14:22:56Z"
---

# Normative Specification

The sole normative source is `requirements-v2-prototype.md` version `2.0-prototype`.
The pre-existing `requirements.md` version 2.7 and OKF summaries derived from it are stale superseded artifacts.
They do not add acceptance criteria, permissions, gates, or product scope.

The specification makes readiness evidence part of the contract:

- The unified Gate 0 must close before Gate 1, evidentiary Direct API integration, or any external write begins.
- Acceptance is determined by the capability matrix and atomic acceptance cases.
- The result is `PROVEN` only when every mandatory capability is proven and the complete closed-loop scenario succeeds on one allowlisted campaign.

An OKF concept may summarize these rules but must not introduce a new acceptance criterion, parameter value, permission, or exception.

# Citations

[1] [`requirements-v2-prototype.md`](../../requirements-v2-prototype.md)

[2] [Source Authority](source-authority.md)
