---
type: Delivery Model
title: Delivery Gates and Evidence
description: Maps delivery gates to standalone, read-only production, test-contour, and paired regression evidence.
tags: [implementation, delivery, evidence]
timestamp: "2026-07-30T12:00:00Z"
---

# Delivery Gates and Evidence

Delivery advances through evidence gates rather than feature-complete claims:

1. Gate 0 establishes the approved three-edition scope, module contract, credential matrix, read-only production boundary, roles, and technical reviews.
2. Gate 1 preserves the deterministic safe core and adds the versioned module seam without changing legacy behavior.
3. Gate 2 proves headless standalone behavior, the local campaign contract lifecycle, the test goal lifecycle, and approved test adapters.
4. Gate 3 proves real production reads, linked analytics, scheduled monitoring, and shadow proposals without writes.
5. Gate 4 proves the unchanged paired Dashboard flow, both authority modes in test, readback, kill switch, observation, ImpactReport, and the post-change LLM decision.

Local contract evidence and live capability evidence are deliberately different.
A synthetic v501 fixture can prove serialization, schema validation, error handling, and reconciliation logic.
It cannot prove account rights, endpoint availability, moderation, platform state transitions, or permission to use a method in production.
Each write operation is accepted only as `LOCAL_CONTRACT`, `TEST_COUNTER`, or `TEST_CONTOUR` evidence.
No gate or evidence status authorizes production write.

Acceptance is traceable by edition, requirement ID, fixture, status, reason code, timeout, and evidence references.
Each run stores only artifacts for stages that actually occurred.
Each edition's final report must include every applicable mandatory capability and cannot treat a missing row or missing evidence as success.
The paired report additionally requires Dashboard regression evidence.

# Citations

[1] [`requirements-modularization-v1.md`](../../requirements-modularization-v1.md), gate, capability, evidence, and acceptance matrices.

[2] [`requirements.md`](../../requirements.md), sections 6.2, 13, 17 through 21, and `FR-CAM-008` for inherited behavior.

[3] [External Write Safety](../runbooks/external-write-safety.md)
