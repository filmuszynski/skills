# ADR 0016: HTML review frames each page on its own `<slug>.localhost` origin

**Status:** Accepted (01.10.2026).

## Context

HTML review shows a reviewed page inside the review shell. The page brings its own
CSS and scripts, which must not touch the shell, and it may use root-absolute paths
(`/img/x.png`) that only resolve when the page sits at the root of an origin. Two
reviews open at the same time must not share storage. The open question was whether
browsers load a frame from `http://<slug>.localhost:<port>/` without any setup. The
Phase 0 spike answered it (`docs/spikes/2026-10-01-html-review-phase-0-findings.md`).

## Decision

- The review server runs a second listener on its own port + 100 that serves reviewed
  pages, routed by the Host header `<slug>.localhost:<port>`. Any other Host gets `403`.
- Each review is the root of its own origin. The shell stays on `127.0.0.1:<port>`.
- The listener binds `127.0.0.1` and, where available, `::1`. Browsers reached an
  IPv4-only listener in the spike, but macOS and Linux resolve `localhost` names to `::1`
  first, and the second bind costs nothing.
- A probe script is injected into every HTML response. Strict CSPs are handled by adding
  a fresh nonce to the policy, in the header and in `<meta>`, and on the probe's tag.

## Consequences

- Root-absolute paths work, and the page's CSS and scripts never meet the shell's.
- The page runs on an origin that is cross-site to the shell, so it cannot read the
  shell's storage or post settings.
- **Cookies:** a cross-site frame never gets `SameSite=Lax` cookies, the browsers'
  default, and Safari sends it none at all. A page that needs a login session, such as
  a dev server with a login, does not stay logged in inside the frame. HTML review
  states this limit rather than working around it.
- It works in Chrome, Edge, Firefox, Safari and the VS Code built-in browser without
  touching the hosts file.

## Alternatives

- **Path prefix on one origin** (`127.0.0.1:<port>/<slug>/`). Loads everywhere, but
  breaks root-absolute paths in static files. It would have been the fallback had Safari
  failed; Safari passed.
- **A shell on a `localhost` name, to make the frame same-site.** Tested: every
  `*.localhost` name is its own site, so the cookies stay blocked.
- **Injecting the shell into the page itself.** No second origin, but the page's styles
  and scripts collide with the shell, and width presets become impossible.
