# ADR 0009: Hooks launch Python through a python3-then-python chain

**Status:** Accepted (30.09.2026, from the Phase 0 spike)

## Context
Plugin hooks run a shell command, and the Python command name differs by system. On Windows
`python3` is often the Microsoft Store alias, which prints "Python was not found" and does
nothing; on macOS and Linux `python` is often missing. See `docs/spikes/2026-09-30-phase-0-findings.md`.

## Decision
Every hook command is `python3 "${CLAUDE_PLUGIN_ROOT}/…" 2>/dev/null || python "${CLAUDE_PLUGIN_ROOT}/…"`,
with the plugin root always quoted.

## Consequences
One command string works on all three systems without a per-platform manifest. A machine with
neither name on PATH gets no plan pages; the README troubleshooting section covers it.

## Alternatives
`python` alone (misses macOS/Linux); `py -3` (Windows only); a per-platform launcher script
(more files, same result).
