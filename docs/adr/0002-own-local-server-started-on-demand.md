# ADR 0002: Own local server, started on demand

**Status:** Accepted (30.09.2026)

## Context
Rebuild-on-request, pruning and settings saved from the page all need something running. Settings must reach the renderer, which `localStorage` cannot do.

## Decision
A standard-library Python server on `127.0.0.1:7777`, started detached by the renderer, stopping after 12 hours idle.

## Consequences
No extra install; the `file://` fallback still works for review. A background process exists on the user's machine.

## Alternatives
No server (no rebuild, page-only settings); a server users start themselves (beginners forget it).
