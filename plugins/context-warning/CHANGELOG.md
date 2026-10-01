# Changelog: context-warning

All notable changes to the context-warning plugin. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the plugin uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-10-01

First public release.

### Added
- A coloured line in the terminal once a session uses 30% (yellow), 40% (orange) and
  50% (red) of its context window. From 30% it shows on every prompt you send.
- During tool calls the line shows only when a new level is first crossed.
- Claude gets a short note once per level, so the reminder does not fill the window.
- The window size (200k or 1M) is read from the session's transcript and follows
  `/model` switches. `CLAUDE_CONTEXT_WINDOW` overrides it.
- After `/compact`, levels above the new usage can fire again.
