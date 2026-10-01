---
name: review-md
description: Render Markdown documents, plans and choice screens as review pages, and apply the feedback to the Markdown source. Loaded by the review-doc skill for .md and .markdown files; also usable directly as /review-doc:review-md <file>. Covers document review, the automatic plan pages, anchored comments, and options or explainer screens for questions that need a picture.
---

# review-md

The Markdown half of review-doc. Load `review-doc:review-doc` too if it is not loaded:
it holds the handover, the exit codes, the verdicts and the extension offer, and this
skill does not repeat them.

## Running the renderer

`<base>` is the "Base directory for this skill" line shown when this skill loaded. The
renderer is `<base>/../../presenter/build_screen.py`. `<python>` means `python3` on
macOS and Linux and `python` on Windows, where `python3` is often only the Microsoft
Store alias. Pages go to `~/.review-doc/pages/` and are served by
a small local server that the renderer starts on its own.

## Reviewing a document

Anything that is prose rather than a plan (notes, a briefing, a README, an article
draft) renders with the `doc` kind:

```bash
<python> "<base>/../../presenter/build_screen.py" doc "<file.md>"
```

Hand the page over as `review-doc:review-doc` describes. A document page differs from a
plan page in a few ways:

- **Two buttons, not three:** Approve and Request changes. A draft has no approach to
  decline, only text to change.
- `##` and `###` headings are both reviewable blocks, and everything above the first
  heading is an Intro block. A document with no headings renders as one block.
- The same file always gets the same page and the same link.

## Plans render themselves

A hook renders every `.md` file Claude writes or edits under a `.claude/plans/` folder,
the project's or `~/.claude/plans/` (Claude Code's default), except inside an
`archive/` folder, and hands you the link as additional context. It exists because plan
mode forbids writing any file except the plan itself; hooks run anyway. Do not call the
renderer yourself while planning. Hand the link over as the hook's text says.

To render a plan by hand, outside plan mode:

```bash
<python> "<base>/../../presenter/build_screen.py" plan "<plan.md>"
```

## After the feedback

**Never hand-edit a generated page.** Edit the Markdown source, then render it again
with the same command. The link does not change. A page that is already open notices
that its source changed, shows a Reload strip, and the server rebuilds it on the next
request.

After a change request, render again as usual. The open page reloads itself once the new build is in, so do not ask the user to reload; still hand the link back.

Comments are anchored to their text, not to a position. Inserting a section above a
commented one does not move the comment, and whitespace or line breaks never break a
match. A passage that was edited is found again by its start and end; one that is gone
hangs its comment on the section's heading. Either way the pasted answer adds
"(the text has changed since)". If you see that note, it usually means you rewrote the
passage, which is often exactly right.

Pages are deleted `stale-hours` after their last build (96 by default). A link to a
deleted page says so; render the file again to get it back.

## What the page offers

So you can answer questions about it: comments and rewrites sit on the text as
highlights that open a bubble; each block has a tick (undecided, approved, declined) and
a pencil for a note; Markdown tables are editable cell by cell in Edit mode; three
counters in the header step through comments, rewrites and all feedback; undo, redo and
a two-click reset sit at the right; Ctrl and the mouse wheel scale the text. The footer
holds the assembled answer and the buttons that finish the review. The page also works
opened as a file, where copying falls back to an older clipboard method.

## Advanced: choice screens

For a question whose answer depends on seeing something, write a screen file to
`~/.review-doc/screens/<name>.md` (any other place works too) and render it:

```bash
<python> "<base>/../../presenter/build_screen.py" screen "~/.review-doc/screens/<name>.md"
```

Expand `~` to the real home folder in the command. Screens are switched off with the
`choice` setting.

**An options screen.** Each `##` becomes a card, lettered A, B, C; the reader picks by
clicking a card's header row.

```markdown
---
kind: options
title: Where should the feedback live?
select: one          # or: many
---

## Sidebar
<svg viewBox="0 0 120 60" width="120" height="60"> … </svg>
Always visible. Costs 400px of width.

## Overlay bubbles
<svg viewBox="0 0 120 60" width="120" height="60"> … </svg>
Full width for the document.
```

Raw HTML and inline SVG pass straight through, which is the reason to use a screen at
all: draw the difference instead of describing it. Two cards that are only prose belong
in the terminal picker. The answer comes back led by `CHOSEN: B (Overlay bubbles)`.

**An explainer.** `kind: explain`, no `select`. Each `##` is a section, nothing is
pickable, and only what did not land comes back. Answer those gaps.

Keep a screen to one question. Two questions on one page get one answer.
