---
type: Implementation Contract
title: Core Contracts and State
description: Summarizes typed snapshots, versioned campaign drafts with priority goals and responsive ads, proposals, approvals, execution state, Dashboard decision history and outcomes, boundaries, and run artifacts.
tags: [implementation, contracts, state]
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
---

# Core Contracts and State

`IntegratedPerformanceSnapshot` binds allowlisted organization, connection, account, campaign, counter, and goal identifiers to a period, attribution model, source timestamps, watermarks, raw metrics, calculated metrics, current managed values, object states, change history, business objective, data-quality gaps, comparability, and conclusion confidence.
Its identifier covers every normative input, configuration version, and policy version.
A late conversion creates a new snapshot version instead of mutating an old one.[^requirements-v2]
Every model-visible and persisted contract is versioned and closed to unknown fields.
Machine-readable JSON Schemas in `schemas/` must match `requirements-v2-prototype.md`; that sole normative source wins until an approved revision supersedes it.
Identifiers, timestamps, money, limits, and evidence references are validated outside the LLM.

`OptimizationProposalV1` is a closed-schema model output.
It records one of `EFFECTIVE`, `INEFFECTIVE`, `INSUFFICIENT_DATA`, or `NEEDS_HUMAN`, observed facts, up to three ranked hypotheses, evidence references to fields present in the snapshot, bounded atomic actions, risks, preconditions, rollback conditions, expected direction, and a short Russian explanation.
Unknown fields and arbitrary HTTP payloads are rejected.

`CampaignDraftV1` names the campaign, describes its supported test structure and business goal, and passes deterministic validation before the confirmed creation lifecycle.
`GoalCandidate` describes a new goal in the test counter and remains `CANDIDATE` until technical event evidence and separate human confirmation establish an approved business meaning.
The Dashboard stores append-only versions of one local campaign draft and exposes its placement settings, business goal, target CPA, strategy, payment model, attribution model, and policy-bound Metrika counter on the separate `Рекламная кампания` page.
The page stores from one to 30 goals with names, events, site locations, types, sources, conversion-value modes, conversion values, and exactly one primary goal.
The same page stores ad groups with keywords, negative keywords, autotargeting categories, and responsive ads containing up to seven titles, three texts, destination and display URLs, sitelinks, callouts, and prepared images.
Exactly one selected group and two ads assigned roles A and B project into `CampaignDraftV1` for the current Gate 0 lifecycle.
Additional goals, groups, and ads remain versioned local draft data.
Saving the draft performs no external write, while subsequent analysis and safe lifecycle simulations consume the selected primary goal, target, pilot group, and A/B ads.
`Вебвизор` remains the last disabled gray navigation item and has no route until the capability is implemented.
The Dashboard history page separates the decision journal from decision outcomes with two top-left tabs.
The journal returns the three newest entries by default and uses server-side pages of ten entries when expanded.
Each decision can open an outcome view that combines its accepted action and immediate execution result with an immutable linked post-change observation.
If no linked observation exists, the view explicitly remains pending instead of presenting synthetic before-and-after evidence.

The single-use `Approval` binds the exact canonical plan to scope, snapshot timestamps, policy version, expected fingerprint, and expiry.
The decision idempotency key covers the current analytical and managed state.
The execution key additionally covers the approved proposal, action, target value, and expected object version.

SQLite stores an `ExecutionLedger` with a unique execution key and transitions through `RESERVED`, `IN_FLIGHT`, and a terminal or blocking result such as `APPLIED`, `NO_CHANGE`, `BLOCKED`, `UNKNOWN_RESULT`, or `FAILED`.
The state survives restart, prevents duplicate application, and blocks further writes after an unresolved unknown result.

Each run uses `runs/<run_id>/` and creates only the artifacts for stages that occurred.
Possible artifacts include `proposal.json`, `approval.json`, `change_diff.json`, `result.json`, `impact_report.json`, `report.md`, and `events.jsonl`.
They record schema and policy versions, evidence, decisions, before-and-after values, provider usage, cost, and timing without secrets or hidden model reasoning.

[^requirements-v2]: [MOX-ADV prototype requirements](../../requirements-v2-prototype.md), `FR-001`, `FR-005`, `FR-007` through `FR-009`, and `NFR-004`.
Every model-visible tool returns exactly one typed result, including denials, timeouts, and internal errors.
Side-effecting tool requests must become persisted Proposals before the executor can consider them.
