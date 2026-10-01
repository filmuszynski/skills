# ADR 0015: context-warning is a second plugin, ported to Python

**Status:** Accepted (01.10.2026).

## Context

The author ran a context-window warning hook written in Node, wired by hand into the
global `settings.json`. It is useful to others, and this repository is already a
marketplace with room for more than one plugin. The repository's rules ask for Python
3.10+ with the standard library only, and Claude Code's native installer does not
install Node.

## Decision

- The hook ships as a second plugin, `plugins/context-warning/`, in this marketplace.
- It is ported to Python and launched through the same chain as review-doc (ADR 0009).
- It keeps its own `CHANGELOG.md` and version in its own `plugin.json`. The root
  CHANGELOG and the `v*` tags stay review-doc's; context-warning has nothing to build,
  so it gets no release tag.
- The author removes the hand-wired hook and uses the plugin (as in ADR 0007).

## Consequences

- One marketplace, one `marketplace add`, two plugins.
- Anyone who has review-doc already has the Python it needs.
- The repository now holds two version lines; each plugin's tests check its own.

## Alternatives

- **Its own repository.** Independent, but a second repo to keep up for about 150 lines.
- **Keep Node.** No port, but a second language here, and a silent no-op wherever
  `node` is missing.
