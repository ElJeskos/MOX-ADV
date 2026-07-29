# Domain docs

This repository uses a single-context domain documentation layout.
The engineering skills must use these rules when exploring the codebase.

## Before exploring, read these

- Read `CONTEXT.md` at the repository root.
- Read relevant ADRs under `docs/adr/`.

If either path does not exist, proceed silently.
Do not flag its absence or suggest creating it in advance.
The `domain-modeling` skill, reached through `grill-with-docs` and `improve-codebase-architecture`, creates domain documentation lazily when terms or decisions are resolved.

## File structure

```text
/
├── CONTEXT.md
├── docs/
│   └── adr/
└── src/
```

## Use the glossary vocabulary

When output names a domain concept in an issue title, refactoring proposal, hypothesis, or test name, use the term defined in `CONTEXT.md`.
Do not drift to synonyms that the glossary explicitly avoids.

If a required concept is absent from the glossary, reconsider whether the term belongs to the project.
If it represents a real gap, note it for `domain-modeling`.

## Flag ADR conflicts

If output contradicts an existing ADR, surface the conflict explicitly instead of silently overriding the decision.

> Contradicts ADR-0007 (event-sourced orders), but may be worth reopening because...
