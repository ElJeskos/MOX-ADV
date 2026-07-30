---
type: Product Scope
title: Prototype Outcome and Scope
description: Defines the proof goal, mandatory pilot boundary, and explicit non-goals.
tags: [product, scope, pilot]
timestamp: "2026-07-29T14:10:28Z"
---

# Prototype Outcome and Scope

MOX-ADV must prove that linked advertising facts can become an explainable, policy-bounded action, be executed safely, and be evaluated on the same campaign.
The required control loop is:

`linked data -> validated snapshot -> analysis -> proposal -> policy check -> approval or mandate -> write -> readback -> observation -> ImpactReport -> post-change LLM analysis -> new typed decision`

The prototype has two functional modules.
Monitoring joins Yandex Direct and Yandex Metrica statistics, calculates metrics, detects anomalies, and evaluates change outcomes.
Campaign management drafts, creates, launches, and safely changes advertising objects through typed commands.

The mandatory pilot is intentionally narrow:

- One organization, allowlisted account, Metrica counter, and prototype-created campaign are in scope.
- The supported campaign shape is one Unified Performance Campaign on search with one group, one targeting condition, and one `ResponsiveAd` with tightly bounded variants.
- The system must demonstrate both human-approved and bounded-autonomous execution, including a separately mandated first launch when it is not part of the approved creation saga.
- The system must produce local contract evidence and controlled-pilot evidence for the operations actually used.

Important non-goals include multi-tenant operation, multiple campaign types, CRM or revenue attribution, automatic media generation, destructive production cleanup, a web UI, cloud deployment, microservices, and guaranteed KPI improvement.
The prototype proves measurement and control safety, not causal uplift.

# Citations

[1] [`requirements-v2-prototype.md`](../../requirements-v2-prototype.md)

[2] [Closed Control Loop](../architecture/closed-control-loop.md)
