# ADR 0007: The author switches to the public plugin

**Status:** Accepted (30.09.2026)

## Context
Two copies of the presenter would drift, and every fix would have to be made twice.

## Decision
After the v1.0.0 acceptance run, the author installs the public plugin and removes the private presenter, hook, command and ring routes.

## Consequences
One codebase; the author hits bugs first. Marks stored under the old port are lost.

## Alternatives
Keep both (drift); switch later (delays the payoff).
