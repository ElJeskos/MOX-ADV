# Prototype isolation

Use this workflow whenever a `wayfinder:prototype` ticket produces code or another repository artifact.

## Start

1. Before creating prototype artifacts, invoke `/worktree prototype/<short-name>` from the repository.
2. Continue every prototype tool call inside the returned `WORKTREE_PATH`.
3. Keep one design question per prototype branch and mark its artifacts as throwaway.
4. Link the branch and runnable artifact from the prototype ticket.

The `/worktree` invocation is standing permission to create the dedicated local and remote prototype branch. It is not permission to create branches for non-prototype work.

## Review

The human tests the prototype in its isolated worktree. Record what the prototype demonstrated and choose exactly one outcome:

- **Discard** — preserve the verdict on the ticket, then remove the prototype branch and worktree.
- **Refine** — continue on the same branch while it answers the same question; use a new prototype branch if the question changes.
- **Integrate** — record the validated decision, then explicitly choose which changes to reimplement cleanly or promote. A prototype branch is never merged automatically.

After discard or completed integration, remove the prototype worktree and local/remote branch. The main branch retains only validated production work and context pointers to the prototype evidence.
