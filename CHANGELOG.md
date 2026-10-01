# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.3] - 2026-10-01

### Changed
- Every button in the header from the Comment / Edit text switch to the right is now
  as tall as the feedback counters, so the row reads as one line of buttons.
- The Comment / Edit text switch slides its highlight from one half to the other
  instead of jumping. Both halves are the same width, the labels sit 1px higher, and
  the slide is off under reduced motion.

## [1.0.2] - 2026-10-01

### Fixed
- A plan's At a glance keeps everything written under a field in that field's row, in
  the order written: a quote, list, table or code block now sits right under the line
  that introduces it instead of below the whole table. Text before the first field
  leads above the table. A plan without a `#` title keeps its fields, and a `---`
  straight under a field's text no longer turns that text into a heading.
- Code fences in plans close the way Markdown closes them: only on the same character,
  at least as long. A ``` line inside a ```` or ~~~ example no longer ends the block
  early, and a fence that never closes is read as text instead of swallowing the
  rest of the plan.
- The page type pill stays in front of the title when a cut-off title is shown whole;
  only the buttons slide away.
- The Request changes icon sits 1px lower than in 1.0.1.

### Changed
- The footer line is left-aligned again.

## [1.0.1] - 2026-10-01

### Added
- A `tooltips` setting (on by default) to switch off the labels that explain each
  button. In ⚙ Settings on every page and as `/review-doc:settings set tooltips off`.

### Changed
- The page type is now a coloured pill in front of the title: MD orange, PLAN dark
  red, CHOICE dark blue, and HTML light blue for when HTML pages arrive. Options
  and explainer screens both say CHOICE.
- The Request changes icon sits 2px higher, with 2px more space before its label.

### Fixed
- The page footer spells the author's name Muszyński, and the footer line is centred.
- A plan page no longer drops a quote, list or code block that sits between the header
  fields; it shows under the At a glance table. A list or code line under a field is no
  longer glued onto that field.

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
