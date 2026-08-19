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

### Integration interaction boundaries

- Work with Yandex Direct and Yandex Metrica exclusively through their APIs; their browser-based personal cabinets are out of bounds.
- Work with the local Dashboard at `http://127.0.0.1:8878/` exclusively through its UI using Playwright; direct Dashboard API calls and direct state manipulation are out of bounds.
