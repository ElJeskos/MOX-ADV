## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for `ElJeskos/MOX-ADV`; external pull requests are not a triage surface.
See `docs/agents/issue-tracker.md`.

### Triage labels

The repository uses the canonical `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix` labels.
See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository with `CONTEXT.md` and `docs/adr/` at the repository root.
See `docs/agents/domain.md`.

### Knowledge bundle

Use `okf/` as the portable living knowledge bundle for this project.
Read `docs/agents/okf.md` before consuming or updating the bundle.
Keep project knowledge in OKF and repository-specific producer and consumer workflow in the adapter.
