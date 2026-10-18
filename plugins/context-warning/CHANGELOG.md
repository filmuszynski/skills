# Changelog: context-warning

All notable changes to the context-warning plugin. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the plugin uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.2] - 2026-10-18

### Fixed
- Claude 5 models count as 1M even when the model id has no `[1m]` suffix. Claude Code
  writes plain `claude-opus-5-5` after `/model` → Opus 5.5, and the plugin read that as
  200k: a session at 116k tokens showed "58% of 200k" instead of staying quiet at 12%.
  Older generations (Claude 4.x, 3.x) still need `[1m]` for 1M.

## [1.0.1] - 2026-10-01

### Changed
- A 1M window is shown as `1M` instead of `1000k`, e.g. `(430k of 1M tokens)`.
- README: sessions that were already open when the plugin was installed need
  `/reload-plugins`; `/clear` does not load it.

## [1.0.0] - 2026-10-01

First public release.

### Added
- A coloured line in the terminal once a session uses 30% (yellow), 40% (orange) and
  50% (red) of its context window. From 30% it shows on every prompt you send.
- During tool calls the line shows only when a new level is first crossed.
- Claude gets a short note once per level, so the reminder does not fill the window.
- The window size (200k or 1M) is read from the session's transcript and follows
  `/model` switches. `CLAUDE_CONTEXT_WINDOW` overrides it.
- After `/compact` the line pauses until the next reply reports the new usage, and all
  levels can fire again.
- Parallel tool calls cannot corrupt the state: it is written to a temp file and renamed.
