# ADR 0021: In the Claude desktop app, Claude opens pages in the app's browser pane

**Status:** Accepted (29.10.2026). Adds to ADR 0005.

## Context

The renderer opens each new page itself: in VS Code's built-in browser inside a VS Code
terminal with the opener extension, in the system browser everywhere else. The Claude
desktop app runs Claude Code sessions too, and there "everywhere else" meant a system
browser window popping up beside an app that has a browser pane of its own.

No process outside the app can open a page in that pane. Only Claude can, through the
app's preview tool. The app marks every session it runs with
`CLAUDE_CODE_ENTRYPOINT=claude-desktop`, and hooks inherit that environment.

## Decision

When `CLAUDE_CODE_ENTRYPOINT` is `claude-desktop` and the link is `http`, the renderer
opens nothing and reports `"opened": "claude-desktop"`. The `vet` skill and the plan
hook's context then tell Claude to open the url in the app's browser pane. A `file://`
link (no server) still goes to the system browser, since the pane is meant for served
pages.

## Consequences

- Inside the desktop app nothing pops up outside it. The url and path are still handed
  over, so the page opens anywhere else too.
- Opening now depends on Claude following the skill. If it does not, the page is not
  opened at all, but the two lines are still there.
- The check rests on an environment variable the app sets. If the app renames it,
  pages fall back to the system browser, which is the old behaviour.

## Alternatives

- **A setting (`open-in pane`).** Needs the user to know about it, and the right answer
  is already known from the environment.
- **Skill text only, with `--no-open` on every call.** Leaves the plan hook opening the
  system browser, since the hook renders without Claude.
