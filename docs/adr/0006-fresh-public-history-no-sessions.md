# ADR 0006: Fresh public history; session context never committed

**Status:** Accepted (30.09.2026)

## Context
The code grew up in a private repo that has customer work in its history. The project convention commits curated session captures.

## Decision
New repo with fresh history; files are copied, not commits. `sessions/` is gitignored in full, and the archive hook lives in the gitignored `settings.local.json`.

## Consequences
Nothing private can surface through history. Session captures exist only locally.

## Alternatives
Filtering the private history (risky, easy to miss something).
