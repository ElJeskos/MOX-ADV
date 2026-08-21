# Issue tracker: GitHub

Issues and specs for this repository live as GitHub issues in `ElJeskos/MOX-ADV`.
Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`.
  Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments with `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`.
- **Apply or remove labels**: `gh issue edit <number> --add-label "..."` or `gh issue edit <number> --remove-label "..."`.
- **Close an issue**: `gh issue close <number> --comment "..."`.

Infer the repository from `git remote -v`.
The `gh` CLI does this automatically when run inside the clone.

## Pull requests as a triage surface

**PRs as a request surface: no.**

The `triage` skill must not pull external pull requests into the issue triage queue.
Collaborators may continue to manage pull requests through their normal workflow.

GitHub shares one number space across issues and pull requests, so a bare `#42` may be either.
Resolve ambiguity with `gh pr view 42`, then fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Wayfinding operations

The `wayfinder` skill uses one issue as a map and child issues as tickets.

- **Map**: Use one issue labelled `wayfinder:map` to hold Notes, Decisions-so-far, and Fog.
  Create it with `gh issue create --label wayfinder:map`.
- **Child ticket**: Link an issue to the map as a GitHub sub-issue through the sub-issues API.
  If sub-issues are unavailable, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body.
  Use a `wayfinder:<type>` label, where the type is `research`, `prototype`, `grilling`, or `task`.
  Assign the ticket to the driving developer after it is claimed.
- **Blocking**: Use GitHub's native issue dependencies as the canonical, UI-visible representation.
  Add an edge with `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`.
  Obtain `<blocker-db-id>` with `gh api repos/<owner>/<repo>/issues/<number> --jq .id`; it is not the issue number or `node_id`.
  If dependencies are unavailable, put `Blocked by: #<number>, #<number>` at the top of the child body.
  A ticket is unblocked when every blocker is closed.
- **Frontier query**: List the map's open children, discard assigned tickets and tickets with open blockers, then select the first remaining ticket in map order.
- **Claim**: Run `gh issue edit <number> --add-assignee @me`.
  Claiming is the session's first write.
- **Resolve**: Comment with the answer, close the ticket, and append a context pointer with its link to the map's Decisions-so-far section.

## Classical delivery handoff

Wayfinder is planning-only in this repository. Its map and children resolve decisions; they do not form the implementation backlog. A `wayfinder:task` is limited to prerequisite work that unblocks a decision.

When a map has no open in-scope decisions or fog:

1. Run `to-spec` on the map issue to publish one implementation-ready spec.
2. Run `to-tickets` on the accepted spec to publish approved vertical implementation slices with native blockers and `ready-for-agent`.
3. Run `implement` for one frontier ticket per fresh session.
4. Verify acceptance criteria and close the ticket manually after implementation so blocked tickets can enter the frontier.

Implementation tickets reference the spec, not the Wayfinder map, and never carry `wayfinder:*` labels. Do not put execution overrides in Wayfinder map Notes. See `docs/agents/delivery-workflow.md` for the complete stage boundaries and short paths.
