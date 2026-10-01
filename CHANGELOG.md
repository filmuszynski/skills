# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-10-01

First public release.

### Added
- `/review-doc:review-doc <file>` and `/review-doc:review-md <file>`: a review page for
  any Markdown document. Comment on any passage, rewrite text in place, approve or
  decline sections, then finish with Approve or Request changes, which copies one answer
  to paste back.
- Plan review: every plan Claude writes under a `.claude/plans/` folder gets its page
  automatically, with Approve, Decline and Request changes, and a decision per step.
- Choice screens: options as cards to pick from, and explainer screens.
- A local server on `127.0.0.1`, ports 7777 to 7787, started on demand and stopped
  after 12 idle hours. It rebuilds a page whose Markdown changed and deletes pages
  older than `stale-hours`. An open page offers to reload when its source changes.
- Six settings (`stale-hours`, `auto-open`, `md`, `html`, `plan`, `choice`), in the
  page under Settings and through `/review-doc:settings [show | set <name> <value> | reset]`.
- New pages open on their own: in VS Code's built-in browser inside a VS Code terminal
  with the opener extension, otherwise in the system browser.
- The VS Code opener `filmuszynski.review-doc-opener`, attached to each release as
  `review-doc-opener.vsix` and offered once from a VS Code terminal. It only opens
  review pages on this machine.
- A credit line on every page with the version and a Settings button.
- Requires Python 3.10 or later. Markdown support is bundled, so nothing else needs
  installing. HTML review arrives in v1.1.

[Unreleased]: https://github.com/filmuszynski/skills/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/filmuszynski/skills/releases/tag/v1.0.0
