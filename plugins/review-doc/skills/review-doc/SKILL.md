---
name: review-doc
description: Review a Markdown document or a plan in the browser instead of the terminal, and read the user's verdict back. Use when the user asks to review, mark up, comment on, proofread or approve a document ("review this", "let me mark this up", "show me that properly", "/review-doc"), when a review-doc hook has just handed you a plan link, when you finish a draft the user is meant to react to, and when the user pastes back feedback from a review page (a block that starts with Review of the plan, Review of the document, Answer to or Questions on).
---

# review-doc

Terminal text cannot be marked up. A review page lets the user point at one sentence
and comment on it, rewrite a line in place so you can adopt their wording, and approve
or decline each section, then paste one block back to you. This skill holds what every
file type shares: when to offer a page, how to hand it over, and what the answer means.

## Running the plugin's scripts

When this skill loaded, Claude Code showed a line "Base directory for this skill:
<path>". Call that path `<base>`. The renderer is
`<base>/../../presenter/build_screen.py`, the extension helper is
`<base>/../../presenter/extension.py` and the settings command is
`<base>/../../presenter/settings.py`. `<python>` below means `python3` on macOS and
Linux and `python` on Windows, where `python3` is often only the Microsoft Store alias.
Quote every path.

## Which file types

Route by the file's extension:

| Extension | What to do |
|---|---|
| `.md`, `.markdown` | Load the `review-doc:review-md` skill and follow it |
| `.html`, `.htm` | Say: "HTML review arrives in review-doc v1.1." |
| anything else | Say that review-doc reviews Markdown files (`.md`, `.markdown`) |

The renderer checks the same thing and refuses with exit 4 (see below), so a wrong
guess costs nothing.

## When to offer a page

Offer a page, in one line, whenever you finish a draft the user is meant to react to,
instead of pasting the whole document into the terminal. Render it when they say yes,
or straight away when they asked for a review.

For a question you need answered, the terminal's own picker is usually better:

| Situation | Use |
|---|---|
| Two to four options described in words | Terminal picker |
| A scope, naming or trade-off question | Terminal picker |
| Layouts, wireframes, or two designs side by side | Choice screen (see `review-doc:review-md`) |
| A diagram: data flow, states, components | Choice screen |
| More than four options, or options that need rich formatting | Choice screen |

A question about a visual topic is not automatically a visual question. "Which colour
system?" is words; "which of these two palettes reads better?" is a picture.

## Handing the page over

The renderer prints one JSON line. On exit 0, take `url` and `path` from it and give the
user **both**, each alone on its own line, with nothing else on that line. A path that
wraps in the terminal loses its Ctrl+Click link.

```
http://127.0.0.1:7777/review/<slug>.html
/home/<user>/.review-doc/pages/<slug>.html
```

Then say in one line what they can do there: comment on any passage, rewrite text in
place, approve or decline any section, then press the button that finishes the review
and paste the result back to you. Do not describe the page further; they can see it.

- `"opened"` is `"vscode"` or `"browser"` when the page already opened itself. Still
  hand over both lines: they are how the page is reopened.
- `"server": false` means the local server did not start, and `url` is a `file://`
  link. Say so in one line, using `serverNote` for the reason. Comments and the answer
  still work from the file; the ⚙ Settings button in the page does not.
- `"offerExtension": true`: see "The VS Code extension" below.

## When it does not render

| Exit | JSON | What to tell the user |
|---|---|---|
| exit 3 | `"reason": "disabled", "setting": "<name>"` | That page type is switched off in the settings, and how to switch it back on: `/review-doc:settings set <name> on` |
| exit 4 | `"reason": "unsupported", "message": "…"` | The message, as it is |
| any other | `"error": "…"` | The link is unavailable this time; carry on in the terminal. The Markdown is never touched by the renderer, so nothing is lost |

Plans are rendered by a hook, which stays silent when `plan` is switched off. If the
user asks why a plan got no page, run `<python> "<base>/../../presenter/settings.py" show`
and show its output.

## When the answer comes back

Pasting is the telling. There is no file to read and nothing to check. The pasted block
starts with a header line that names the page:

| Header | Page |
|---|---|
| `Review of the plan "…" (…):` | a plan |
| `Review of the document "…" (…):` | a document |
| `Answer to "…" (…):` | an options screen |
| `Questions on "…" (…):` | an explainer screen |

On a plan or a document, a `VERDICT:` line follows the header when the user pressed a
verdict button, then the comments, decisions and rewrites. Act on the verdict:

- **approved** means go ahead, applying anything else in the block, and do not come
  back for another review. With nothing marked, the block stops at the verdict line.
- **revise and re-present** means apply everything listed, render the page again and
  hand the link back. Do not start building until they have seen it. This is the only
  verdict that asks for another round.
- **declined** (plans only) means stop. Do not patch the plan; rethink the approach and
  come back with a different one.

An `Answer to` block carries a `CHOSEN:` line: take the named option as the decision,
or, with `CHOSEN: nothing`, read what they wrote instead. A `Questions on` block lists
only the passages of an explainer that did not land; those are gaps in your
explanation, so answer them.

With no verdict line, the block is still complete feedback. Ask only if you genuinely
cannot tell whether to proceed.

## Settings

Seven settings, changed with `/review-doc:settings` or with ⚙ Settings at the foot of
every page served locally: `stale-hours` (how long pages and unsaved comments are
kept, default 96), `auto-open`, `tooltips`, and the page types `md`, `html`, `plan` and `choice`.

## The VS Code extension (asked once)

When a render result carries `"offerExtension": true`, the user is in a VS Code
terminal without the opener extension and has not been asked. After the handover, ask
once whether review pages should open inside VS Code's built-in browser, through a
small extension from the plugin's GitHub release.

- On yes: `<python> "<base>/../../presenter/extension.py" install`
- On no: `<python> "<base>/../../presenter/extension.py" decline`

Either command records the answer, so never ask again, even if the install failed.
Relay its `message` in one line. A development version has no release to download
from; the message then says to pass `--vsix <file>`.
