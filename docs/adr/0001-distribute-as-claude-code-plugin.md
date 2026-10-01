# ADR 0001: Distribute as a Claude Code plugin from a GitHub marketplace repo

**Status:** Accepted (30.09.2026)

## Context
Users are Claude Code users, many of them beginners. Plan review needs a hook, and hand-editing `settings.json` is the step beginners fail at.

## Decision
The repo is a plugin marketplace; `review-doc` is a plugin carrying skills, commands and the hook.

## Consequences
Two commands install everything, and updates are one command. The library is tied to Claude Code's plugin format.

## Alternatives
`npx skills add` (copies skills only, no hook); manual zip copy (error-prone). Manual install stays documented as a fallback.
