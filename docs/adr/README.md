# Architecture Decision Records

Lightweight MADR style: Context, Decision, Consequences, Alternatives.
"Accepted" means agreed in the design brainstorm of 30.09.2026. Supersede with a new ADR.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-distribute-as-claude-code-plugin.md) | Distribute as a Claude Code plugin from a GitHub marketplace repo | Accepted |
| [0002](0002-own-local-server-started-on-demand.md) | Own local server, started on demand | Accepted |
| [0003](0003-home-folder-and-hashed-slugs.md) | Pages and settings in `~/.review-doc/`, slugs hashed by source path | Accepted |
| [0004](0004-mit-license.md) | MIT license | Accepted |
| [0005](0005-vscode-opener-as-release-vsix.md) | VS Code opener shipped as a `.vsix` on each release | Accepted |
| [0006](0006-fresh-public-history-no-sessions.md) | Fresh public history; session context never committed | Accepted |
| [0007](0007-author-uses-the-public-plugin.md) | The author switches to the public plugin | Accepted |
| [0008](0008-planning-docs-stay-private.md) | Specs and phase plans stay in the private workspace | Accepted |
| [0009](0009-hook-launcher-chain.md) | Hooks launch Python through a python3-then-python chain | Accepted |
| [0010](0010-python-310-and-vendored-markdown.md) | Python 3.10+, with Python-Markdown vendored | Accepted |
| [0011](0011-port-range-single-instance-and-takeover.md) | Port range 7777-7787, one server per home folder, newer version takes over | Accepted |
| [0012](0012-links-name-127-0-0-1.md) | Review links name 127.0.0.1, not localhost | Accepted |
| [0013](0013-opener-version-follows-the-plugin.md) | The opener's version follows the plugin; installed from the matching release | Accepted |
| [0014](0014-public-repo-starts-from-one-commit.md) | The public repo starts from one commit | Accepted |
| [0015](0015-context-warning-second-plugin.md) | context-warning is a second plugin, ported to Python | Accepted |
| [0016](0016-frame-origin-per-review.md) | HTML review frames each page on its own `<slug>.localhost` origin | Accepted |
