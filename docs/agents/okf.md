# OKF Agent Integration

This file configures repository agents as producers and consumers of the portable `okf/` bundle.
It contains workflow instructions only; project knowledge belongs in OKF concepts and authoritative live sources.

## Consume

1. Start at `okf/index.md` and navigate one level at a time through relevant indexes.
2. Use `type`, `title`, `description`, `tags`, `status`, `generated`, and `verified` to route and assess concepts before loading full bodies.
3. Follow cross-links to assemble only the context needed for the task.
4. Read the source-authority concept before changing product or implementation behavior.
5. Inspect `sources` and cited live material whenever authority, precision, trust, or freshness matters.
6. Treat missing optional fields as explicit absence of a signal, not malformed OKF.
7. Tolerate unknown types and fields, missing optional indexes, and broken cross-links.

## Produce

1. Update the authoritative live source before its derived concept when another artifact governs the fact.
2. Keep one coherent concept per non-reserved Markdown file because its bundle-relative path is its identity.
3. Record descriptive metadata, the real producer in `generated`, lifecycle `status`, and available provenance in `sources`.
4. Add `verified` only after the named actor actually checks the current content against its sources.
5. Set `stale_after` only from an explicit freshness policy.
6. Use source IDs and matching Markdown footnotes for claim-level attribution.
7. Update the parent index description, cross-links, source map, and log in the same change.
8. Run the repository-native OKF check after every bundle change.

The bundle targets OKF v0.2 as declared by `okf/index.md`.
