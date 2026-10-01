# ADR 0010: Python 3.10+, with Python-Markdown vendored

**Status:** Accepted (30.09.2026, Phase 1)

## Context
Users should need no `pip install`, and the presenter renders with Python-Markdown. The spec
named Python 3.8, but Markdown 3.8.2 needs `importlib.metadata`, which is in the standard
library only from 3.10. Python 3.8 and 3.9 are end-of-life.

## Decision
Vendor Markdown 3.8.2 unmodified under `plugins/review-doc/presenter/vendor/`, load its
extensions by module path (a vendored copy has no entry points), and require Python 3.10 or later.

## Consequences
Zero installs, and rendering is identical on every machine whatever Markdown the user has
installed. Security fixes to Markdown arrive only when the vendored copy is updated
(`presenter/vendor/README.md` says how). Python 3.8 and 3.9 users get an error; the README
states the requirement.

## Alternatives
Vendor Markdown 3.7 to keep Python 3.8 (an old release, soon unmaintained); require
`pip install markdown` (the most common beginner failure).
