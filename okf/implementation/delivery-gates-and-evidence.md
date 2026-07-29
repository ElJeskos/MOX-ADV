---
type: Delivery Model
title: Delivery Gates and Evidence
description: Maps delivery gates to the evidence needed for local validation and the controlled pilot.
tags: [implementation, delivery, evidence]
timestamp: "2026-07-29T14:22:56Z"
---

# Delivery Gates and Evidence

Delivery advances through evidence gates rather than feature-complete claims:

1. Gate 0 establishes the validated specification, local tooling, secret hygiene, fixed policy parameters, verified live access, roles, keys, credentials, site zones, API contracts, platform caps, and technical reviews.
2. Gate 1 implements the deterministic safe core: schemas, Proposal Store, policy, ledger, authority state, kill switch, secret isolation, and adversarial simulation.
3. Gate 2 proves the local campaign contract lifecycle without Yandex egress and proves the test goal lifecycle.
4. Gate 3 proves linked production analytics, scheduled monitoring, and shadow proposals without writes.
5. Gate 4 proves the controlled pilot, both authority modes, readback, kill switch, observation, ImpactReport, and the post-change LLM decision.

Local contract evidence and live capability evidence are deliberately different.
A synthetic v501 fixture can prove serialization, schema validation, error handling, and reconciliation logic.
It cannot prove account rights, endpoint availability, moderation, platform state transitions, or permission to use a method in production.
Each write operation remains `LOCAL_CONTRACT_ONLY` until a successful allowlisted controlled-pilot call and readback produce live evidence.

Acceptance is traceable by requirement ID, fixture, status, reason code, timeout, and evidence references.
Each run stores only artifacts for stages that actually occurred.
The final report must include every mandatory capability and cannot treat a missing row or missing evidence as success.

# Citations

[1] [`requirements.md`](../../requirements.md), sections 6.2, 13, 17 through 21, and `FR-CAM-008`.

[2] [External Write Safety](../runbooks/external-write-safety.md)
