---
type: Product Scope
title: Prototype Outcome and Scope
description: Defines the three product editions, inherited behavior, integration surfaces, and explicit non-goals.
tags: [product, scope, editions, integration]
timestamp: "2026-07-30T12:00:00Z"
---

# Prototype Outcome and Scope

MOX-ADV has three editions.
Standalone Metrika and standalone Direct are independently installable headless modules for a customer's ecosystem.
The paired Direct and Metrika edition composes those module interfaces and retains the existing local operator Dashboard at `http://127.0.0.1:8878`.
Standalone customers use versioned HTTP/JSON request and result processing.
The paired runtime uses the same contract through an in-process adapter.

The inherited paired outcome remains unchanged.
Linked advertising facts must become an explainable, policy-bounded action, execute safely in an approved test contour, and be evaluated on the same test campaign.
The required paired control loop is:

`linked data -> validated snapshot -> analysis -> proposal -> policy check -> approval or mandate -> write -> readback -> observation -> ImpactReport -> post-change LLM analysis -> new typed decision`

The Metrika module reads or accepts validated Metrika evidence, calculates supported metrics, assesses data quality, and returns recommendations and provenance.
The Direct module reads or accepts validated Direct evidence, calculates Direct-native metrics, evaluates hypotheses, returns recommendations, and applies typed campaign commands only in test.
The paired product preserves the existing linked monitoring, campaign management, calculations, policies, execution semantics, Decision Records, and Dashboard behavior.

The mandatory environment boundary is strict:

- Production permits provider reads, calculations, analysis, recommendations, proposals, and Decision Records only.
- Every campaign, goal, or site-changing operation is rejected before write credential resolution and HTTP when the environment is production.
- Existing write-capable behavior is demonstrated only through explicit test resources or approved test adapters.
- The paired product must prove both human-approved and bounded-autonomous execution in test.

Important non-goals include multi-tenant operation, multiple campaign types, CRM or revenue attribution, automatic media generation, production write, a standalone module UI, cloud deployment, microservices, and guaranteed KPI improvement.
The prototype proves measurement and control safety, not causal uplift.

# Citations

[1] [`requirements-modularization-v1.md`](../../requirements-modularization-v1.md), product, integration, environment, and acceptance matrices.

[2] [`requirements.md`](../../requirements.md), sections 2 and 3 for inherited behavior.

[3] [Closed Control Loop](../architecture/closed-control-loop.md)
