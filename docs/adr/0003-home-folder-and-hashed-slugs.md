# ADR 0003: Pages and settings in `~/.review-doc/`, slugs hashed by source path

**Status:** Accepted (30.09.2026)

## Context
One server serves every project. Two projects can both have a `README.md`.

## Decision
Pages and `config.json` live in `~/.review-doc/`; every slug ends in a 6-character hash of the absolute source path.

## Consequences
Links are stable per file, there are no collisions, and nothing is written into user repos. Pages are not visible in the project folder.

## Alternatives
Pages inside each project (collisions across projects are impossible to serve from one port without a registry).
