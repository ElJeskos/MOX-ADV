# OKF Agent Integration

This file configures repository agents as producers and consumers of the portable `okf/` bundle.
It contains workflow instructions only; project knowledge belongs in OKF concepts and authoritative live sources.

## Consume

1. Start at `okf/index.md` and navigate one level at a time through the relevant indexes.
2. Use concept `type`, `title`, `description`, and `tags` for routing before loading a full body.
3. Follow cross-links to assemble only the context needed for the task.
4. Read `okf/project/source-authority.md` before changing product or implementation behavior.
5. Inspect cited live sources whenever authority, precision, or freshness matters.
6. Tolerate unknown concept types, unknown frontmatter fields, absent optional indexes, and broken cross-links as required by permissive OKF consumption.

## Produce

1. Update the authoritative live source before its derived concept when the fact is governed elsewhere.
2. Keep one coherent concept per non-reserved Markdown file because its bundle-relative path is its identity.
3. Give each concept a descriptive `type`, `title`, one-sentence `description`, useful `tags`, and an ISO 8601 `timestamp`.
4. Use structured Markdown bodies and normal Markdown cross-links to express relationships.
5. Update the parent `index.md` description, relevant citations, provenance map, and `okf/log.md` in the same change.
6. Preserve source selection, synthesis, ambiguity resolution, and user-facing wording as agent or human judgment.
7. Use deterministic tooling only for mechanical scaffolding and validation.
8. Run `make check-okf` after every bundle change.

The repository targets OKF v0.1 as declared by `okf/index.md`.
Migrating to another OKF version is an explicit bundle-wide change, not an incidental maintenance edit.
