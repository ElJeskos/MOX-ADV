# Delivery workflow

This repository uses the classic planning and delivery sequence from the engineering skills.
`to-spec` is the current name of the former `to-prd` skill.

## Canonical sequence

For a large effort whose route is still unclear:

```text
Wayfinder → to-spec → to-tickets → implement → code-review
```

1. **Wayfinder** resolves product, research, prototype, and prerequisite decisions until the map is clear.
2. **to-spec** collapses the cleared map into one implementation-ready spec issue.
3. **to-tickets** turns the accepted spec into approved tracer-bullet implementation tickets with native blocking edges.
4. **implement** builds one frontier ticket in one fresh session, drives TDD at the agreed seams, validates the result, runs code review, and commits to the current branch.
5. After acceptance criteria are verified, close the implemented ticket manually so its dependants enter the frontier.

Run `to-spec` and `to-tickets` in the same context window when practical so a large spec does not need to be fetched again.

## Stage boundaries

### Wayfinder: decisions only

A Wayfinder map is complete when no in-scope decision remains open and no in-scope fog remains.
Its children are decision tickets:

- `wayfinder:research` establishes an external fact or recommendation;
- `wayfinder:grilling` resolves a product decision with the owner;
- `wayfinder:prototype` creates disposable evidence for a specific unresolved design question;
- `wayfinder:task` performs prerequisite work needed to make a decision.

A `wayfinder:task` does not implement the destination. Production code, integration, E2E delivery, and regression repair belong downstream.

Wayfinder maps in this repository are planning-only. Do not add an execution override to a map's Notes. Do not apply `wayfinder:*` labels to implementation tickets.

### to-spec: one buildable source

When a Wayfinder map clears, invoke `to-spec` on the map issue, not on an individual decision ticket. The spec gathers the distributed decisions, user stories, implementation decisions, test seams, and out-of-scope boundary into one parent issue.

For a settled change that spans several sessions but never needed Wayfinder, start directly at `to-spec`.

### to-tickets: implementation backlog

Invoke `to-tickets` only after the spec is accepted. Review and approve the proposed granularity and blockers before publication. Each published ticket must be a complete, independently verifiable vertical slice sized for one fresh context window.

Implementation tickets reference the spec as their parent. They are not children of the Wayfinder map and do not carry `wayfinder:*` labels. Native blockers define the frontier. Once child tickets are published, remove `ready-for-agent` from the parent spec if an automated runner might otherwise implement the entire spec directly.

### implement: one ticket per session

Invoke `implement` for one unblocked implementation ticket in a fresh session. It consumes decisions; it does not reopen product discovery or reslice the backlog. If the ticket is too large for one context window, return it to `to-tickets` for a smaller vertical breakdown.

`implement` works on the current branch. In this repository that is `main` unless the user explicitly requests a branch. After tests, review, and commit, reconcile the acceptance criteria and close the ticket manually.

## Short paths

- **Small and already decided:** `implement` directly; skip Wayfinder, spec, and tickets.
- **Decided but multi-session:** `to-spec → to-tickets → implement`.
- **Large with unresolved fog:** `Wayfinder → to-spec → to-tickets → implement`.
- **Incoming external issue:** use `triage`; it joins the flow at an agent-ready implementation ticket.

One artifact owns each stage. Never let a Wayfinder map and `to-tickets` create competing implementation backlogs for the same scope.
