# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.1.3] - 2026-10-01

### Changed
- The three counters in the header have no frame and no bar underneath any more. The symbol
  and the number carry the counter's colour (yellow for comments, orange for edits, grey for
  the total), and hover lays a soft plate of that colour behind it.
- The round button has no frame either. Its icon is drawn in the edit orange, with an
  orange plate on hover.

## [1.1.2] - 2026-10-01

### Changed
- The credit line under the document is one centred capsule in four parts:
  "/review-doc skills v.<version> by Filip Muszyński", MIT License, GitHub and Settings.
  The credit part is always in the link colour, and the capsule sits twice as far below the rule.
  The name is no longer a link.
- The settings panel opens without the hours number selected.
- The Settings button draws its gear instead of using the ⚙ character.
- HTML review is now announced for 1.2 (settings panel, skill and the message for `.html` files).

### Added
- Choice screens open a box too after Copy answer or Copy questions, like Approved:
  "Answer copied" or "Questions copied", Close page, Cancel and Copy prompt again.

## [1.1.1] - 2026-10-01

### Changed
- Comments and rewrites from earlier rounds are a light tint on the text instead of
  an underline.
- The round button sits right of the counters, and its "this round" icon is an open ring.
- While an Approved, Declined or Waiting box is open, the header and footer stay
  sharp above the blur, and the header shows the whole title.
- Copy prompt again sits on the left of the box's buttons instead of under them.

### Fixed
- Resizing the window no longer makes an open Approved, Declined or Waiting box and
  its blur vanish while the page stays blocked behind them.

### Added
- The Approved and Declined boxes draw a check or a cross as they open.
- The Waiting box has a small stage where a pixel robot plays sketches until the page
  reloads: typing, juggling, fetching the new version, a bright idea, fishing for bugs,
  dancing, a coffee break and sweeping up typos. It walks on a different way each time,
  never opens on the sketch it opened on last time, and rolls new details on every run.
  With reduced motion it stands still.

## [1.1.0] - 2026-10-01

### Added
- Approve, Decline and Request changes open a box over the dimmed, blurred page
  that says what was copied and what to do next, with a Copy prompt again link
  under the buttons. Close page asks twice, like Reset.
- After Request changes the page waits for Claude's revision and reloads itself
  once the page has been rendered again and the file has stopped changing. Without
  a new render it reloads after 30 seconds of quiet.
- Comments and rewrites from earlier rounds stay on the page as an underline with a
  read-only bubble. A new button left of the counters switches them between this
  round, earlier rounds and every round. Earlier rounds never go back into the prompt.
- Documents show their `**Key:** value` lines in the At a glance box, like plans,
  and comments on it reach the prompt.

### Changed
- A table whose header cells are all empty is shown without its header bar, and its
  first column reads as the header column, as in a plan's At a glance box.
- The Request changes prompt says the open page reloads by itself.
- Reset also clears earlier rounds.

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
