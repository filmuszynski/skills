# ADR 0017: A probe inside the reviewed page, talking to the shell by postMessage

**Status:** Accepted (22.10.2026).

## Context

HTML review shows a reviewed page in a frame on its own origin (ADR 0016). The shell
cannot reach into that document, yet the reviewer must select passages, comment on
them, rewrite text in place and see all of it drawn on the page. Something has to run
inside the page. That something must not change the page's DOM or CSS matches, must
not trust the page it lives in, and must not hand the page the shell's powers.

## Decision

- **The probe** is one script injected into every HTML response, running on the page's
  origin before the page's own scripts. It registers its listeners on `window` in the
  capture phase, so it sees events first and can swallow clicks, form submits and
  typing in Comment and Edit text mode.
- **No wrappers.** The probe never inserts elements into the page's content. Marks and
  underlines are `position: fixed` boxes computed from `Range.getClientRects()`, drawn
  inside one closed shadow root on a single `<review-doc-layer>` element appended to
  `<html>`, with `pointer-events: none`. Comment-mode clicks are hit-tested against the
  boxes.
- **One channel.** Every message is a plain object `{rd: 1, type, ...}`; anything else is
  dropped. The shell accepts a message only when `event.source` is the frame window and
  `event.origin` is the frame's exact origin, and posts with that exact target origin.
  The probe accepts a message only from its parent, and only from one of three loopback
  spellings of the shell (`127.0.0.1`, `localhost`, `[::1]`) on the shell's port, which is
  its own port minus 100. The first accepted `init` fixes the shell origin, and the probe
  posts nothing before it.
- **Whole-state `draw`.** The shell sends the complete list of marks and edits on every
  change, and the probe redraws from it. There are no incremental messages, so first
  load, a new item, undo, redo and reset share one code path.
- **The shell owns the state.** It keeps `state.data`, computes the rewrite runs and the
  revert of a single run, and mints the id of a new edit. The probe never diffs. A `draw`
  edit entry carries two run lists: `runs`, coalesced, which the underlines, the counter
  stops and the revert use, and `fine`, uncoalesced, used only to re-apply a rewrite in
  the page. Coalescing swallows the unchanged bridge words between two changes, so
  applying the coalesced list would pull plain words into a replaced link on undo, redo
  or reload.
- **Replacements keep their formatting.** A replacement is inserted at the first deleted
  real character, so a word replaced inside a link stays inside that link.
- **Messages from the frame are untrusted.** The reviewed page's own scripts run in the
  frame window and pass both the source and the origin check. The shell therefore
  validates every field of every message and accepts only ids it already holds; `null`
  creates a new edit id.
- **A frame document that never says `hello` within 1500 ms** shows the away strip.
- **No `sandbox` and no `allow` attribute on the frame.** The page needs its scripts and
  its own origin's storage. `sandbox` returns those only through `allow-scripts
  allow-same-origin`, a pair that switches the sandbox off. An empty `allow` delegates no
  camera, microphone or location to a page under review. A test pins the absence.

## Consequences

- The page's DOM, selectors and CSS matches stay as they were, apart from the one layer
  element and, while a rewrite is shown, the edited text itself.
- A page script can send forged messages. The worst a forgery does is change the review
  state through ids the shell already has, or add an edit; it cannot reach the shell's
  storage, which sits on another origin.
- Page scripts that listen on `window` in the capture phase before the probe is
  injected cannot be swallowed. The probe loads first in the document, so this concerns
  only scripts added later to `window` capture, which is rare.
- Boxes follow layout only when the probe redraws, so it redraws on resize, scroll and
  load.

## Alternatives

- **Wrapping text in `<mark>` inside the page.** Simpler to find again, but it changes
  the page's DOM and breaks CSS selectors such as `p > a:first-child` and `:nth-child`.
- **A same-origin frame.** No postMessage needed, but the page could then read the
  shell's storage and post to its settings endpoints.
- **`"*"` as target origin.** Works with any frame, but any document the frame navigates
  to would receive the review state.
