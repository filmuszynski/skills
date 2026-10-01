# ADR 0013: The opener's version follows the plugin; installed from the matching release

**Status:** Accepted (30.09.2026, Phase 4). Adds to ADR 0005.

## Context

ADR 0005 ships the VS Code opener as a `.vsix` on each GitHub release and offers it
once. Something has to decide which release to download, and the extension and the
plugin must agree on the link format the renderer hands over. `vsce` rejects
pre-release versions such as `0.1.0-dev`.

## Decision

- The extension's version is the plugin version without its pre-release suffix. A test
  holds `vscode-opener/package.json` to `plugin.json`.
- Every release carries the asset `review-doc-opener.vsix`. The plugin downloads it from
  the tag `v<plugin version>`, so it always installs the extension released with it.
- A development version has no release; `extension.py install --vsix <file>` installs a
  locally built one.
- The renderer decides whether to offer (VS Code terminal, `code` on PATH, extension not
  installed, not asked before) and reports it as `offerExtension`. Installing or
  declining both record the answer.

## Consequences

- One number to keep in step, enforced by a test.
- An older plugin installs the older extension. Both accept the same link format, so that
  is harmless until the format changes; a change of format means a new ADR.
- No automatic extension updates (as ADR 0005).

## Alternatives

- **Always the latest release** (`releases/latest/download/…`). One URL, but a plugin
  could install an extension newer than it understands.
- **An independent extension version.** More freedom, and one more number nobody checks.
