# ADR 0008: Specs and phase plans stay in the private workspace

**Status:** Accepted (30.09.2026)

## Context
The project convention keeps the design spec and each phase plan inside the project. Here they reference the author's private workspace paths, the switch-over of his own setup, and the search terms of the privacy sweep, which are private by nature.

## Decision
Specs and phase plans live only in the author's private workspace. This repo carries the ADRs and the roadmap, which say what was decided and why without private detail. `docs/specs/` and `docs/plans/` are gitignored so a copy cannot slip in.

## Consequences
Contributors see decisions and phases, not the full planning text. Nothing private can reach the public history through planning documents.

## Alternatives
Scrubbed public copies of every spec and plan (a second document to keep in sync, and one missed line leaks).
