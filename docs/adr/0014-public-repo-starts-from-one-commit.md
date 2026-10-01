# ADR 0014: The public repo starts from one commit

**Status:** Accepted (01.10.2026, Phase 5). Applies ADR 0006 to this repo's own history.

## Context

ADR 0006 gave this repo a history separate from the private workspace. Its own early
commits still carried private details: a repository URL, a local port of the author's
setup and a house-rule marker from the ported presenter. Later commits removed them,
but history keeps every version. GitHub also keeps objects reachable by SHA after a
force push, so rewriting branches in place would not remove them.

## Decision

- Before going public, the full private history moves to a local branch
  `archive/private-history`. It is never pushed.
- `main` restarts as one commit holding the 1.0.0 tree.
- The private GitHub repository is deleted and a new public one is created under the
  same name, so nothing from the old history is reachable on GitHub.

## Consequences

- Public history begins at 1.0.0; the record of how it was built stays in the ADRs,
  the roadmap and the CHANGELOG.
- Local clones of the private repo, including the author's plugin marketplace, have
  unrelated history and must be removed and added again.

## Alternatives

- **Filtering the history** (`git filter-repo`). Keeps the commits, but every missed
  string stays public forever. Rejected for the same reason as in ADR 0006.
- **Flipping the private repo to public.** Publishes the early commits as they are.
