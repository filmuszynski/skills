# ADR 0019: Marks, bubbles and the counters reach the page through an anchor backend

**Status:** Accepted (22.10.2026).

## Context

Everything a reviewer leaves on a Markdown page lives on the page itself: a comment is
a `<mark>` around the passage, a rewrite is the edited paragraph, an earlier round is an
underline. `shell.js` drew those marks, positioned bubbles from their rectangles,
stepped the counters through them and scrolled to them, all with DOM ranges on its own
document.

HTML review (1.2) shows the reviewed page in a frame on another origin (ADR 0016). The
shell cannot touch that document. Only a probe script inside the frame can, and the two
talk by `postMessage`. Counters, rounds, undo, the bubbles and the answer should still be
one piece of code for every page kind.

## Decision

- The shell reaches anchored items only through one backend object with six methods:
  - `draw(id)` draws one comment, or, without an id, everything that comes from the
    review state;
  - `stops(kind)` lists the counters' stops for `comments`, `edits` or `all`, in page
    order;
  - `rect(handle)` gives a stop's rectangle in the shell's viewport;
  - `scrollTo(handle)` brings a stop into view and pulses it;
  - `open(id)` lights every piece of one comment or earlier item;
  - `isEarlier(handle)` tells an earlier round's stop from a current one.
- A handle is opaque to the shell. The md backend hands out mark elements.
- Finding a passage again stays inside each backend, because only its own drawing
  needs it.
- Bubbles take an id and a rectangle (`commentBubble`, `earlierBubble`, `askComment`).
  A backend reports a new selection as `{sec, quote, occ, rect, clear, extra}`; `extra`
  carries its own anchor fields into the stored comment.
- A page script registers a backend as `window.REVIEW_DOC_BACKEND`, a factory taking the
  shell's host object. The shell picks it in `start()`. A factory that is missing,
  throws, or returns an object without all six methods falls back to the md backend.

## Consequences

- Markdown, plan and choice pages run the same code as before, moved behind the seam.
- The HTML page needs only a frame backend and the probe; counters, rounds, undo and the
  answer are shared.
- Rewrites, tables, decisions, notes and choices stay md-only for now. HTML rewrites
  (one element, old to new) get their own path when the frame backend is built.
- A broken HTML script cannot break a Markdown review.

## Alternatives considered

- **One shell per page kind.** It duplicates counters, rounds, undo, finish boxes and the
  answer, and the two would drift apart.
- **Mirror the frame's text into the shell's DOM.** The marks would sit on a copy, not on
  the page the reviewer sees, and every layout or script change in the page would break
  the mirror.
