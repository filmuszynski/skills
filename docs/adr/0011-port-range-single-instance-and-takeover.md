# ADR 0011: Port range, one server per home folder, newer version takes over

**Status:** Accepted (30.09.2026, Phase 2). Supersedes the single-port line of ADR 0002;
the rest of ADR 0002 stands.

## Context
ADR 0002 fixed the server on port 7777. Phase 0 showed that the port can be taken, and that
several hooks firing at once start several servers, each overwriting `server.json`. A plugin
update also leaves the old version's server running for up to 12 hours.

## Decision
- The server binds `127.0.0.1` on the first free port of 7777 to 7787.
- Before binding it takes an exclusive OS lock on `~/.review-doc/server.lock`. An instance
  that cannot get it within 2 seconds exits.
- `/api/health` returns `{ok, version, port, pid}`. The renderer trusts a server only when
  `port` and `pid` match `server.json`.
- If the matching server reports an older version, the renderer stops it through
  `POST /api/stop` (same Host, Content-Type and Origin rules as the settings endpoint) and
  starts its own. A same or newer version is used as it is, so two sessions on different
  versions (one not yet reloaded) never stop each other in turn.
- On Windows, `SO_REUSEADDR` is off, so a taken port really counts as taken.
- For tests and unusual setups: `REVIEW_DOC_PORTS=<a>-<b>` changes the range,
  `REVIEW_DOC_NO_SERVER=1` never starts a server, and `REVIEW_DOC_NO_OPEN=1` never opens
  a page.

## Consequences
- Exactly one server per home folder, and the link is stable while it runs.
- The lock is released by the OS on a crash, so a crash never blocks the next start.
- A port change after a restart changes the page origin, and marks stored in the browser
  are per origin. They stay under the old port until that port is used again.
- Any local process can stop the server. It could kill it anyway.

## Alternatives
- A single port with no fallback: breaks on any machine where 7777 is in use.
- An `O_EXCL` lock file: goes stale after a crash and then needs cleanup logic.
- Killing the old server by PID: PIDs are reused, and an HTTP stop is testable in-process.
