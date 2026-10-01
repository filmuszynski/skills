# HTML review, Phase 0 findings (01.10.2026)

The throwaway spike for review-doc 1.2. A small server served a shell page on one port
and the reviewed pages on a second port, routed by `Host: <slug>.localhost`. It
injected a probe script into every framed HTML page, and the probe reported back to the
shell by `postMessage`. The spike code lived on a branch that was deleted afterwards.
Only this file and ADR 0016 remain.

Observed on Windows 11 (Chrome, Edge, the VS Code built-in browser, all visible or
headless), and on GitHub's `macos-latest`, `ubuntu-latest` and `windows-latest` runners
driven over WebDriver (Chrome, Edge, Firefox, Safari).

## Q1. Does `http://<slug>.localhost:<port>/` load in a frame, at the root path?

| Browser | Frame loads | Root-absolute asset (`/img/x.svg`) | Relative asset |
|---|---|---|---|
| Chrome (Windows, macOS, Linux) | yes | yes | yes |
| Edge (Windows, macOS) | yes | yes | yes |
| Firefox (Windows, macOS, Linux) | yes | yes | yes |
| Safari (macOS) | yes | yes | yes |
| VS Code built-in browser (Windows) | yes | yes | yes |
| Edge (Linux) | not observed: the driver failed with HTTP 500 on the runner | | |

- The browsers resolve `*.localhost` themselves. The operating system does not have to:
  on the Windows Server runner `getaddrinfo("site.localhost")` failed outright, and the
  browsers still loaded the frame.
- On macOS and Linux `getaddrinfo` returns `::1` before `127.0.0.1`. The spike's frame
  listener bound `127.0.0.1` only, and every browser still reached it.
- **Path-prefix mode** (`127.0.0.1:<port>/<slug>/`) loads too, but root-absolute assets
  fail in it everywhere, as expected.
- The VS Code opener only opens `/review/<name>.html` links. That holds for HTML review
  pages too, since the shell page is still a review page; only the frame is elsewhere.
- In the hidden automation tab of the author's own Chrome, a framed Vite page fired its
  `load` event after about 10 seconds. That happened without the proxy too, and the same
  page loaded in 414 ms in the visible VS Code browser. It comes from the hidden tab,
  not from the design.

**Chosen for Phase 1: subdomain mode, one origin per review on `<slug>.localhost`.**
Path-prefix mode is not needed as a fallback.

## Q2. Isolation, and the page's own cookies and storage

| Check | Result, all browsers |
|---|---|
| A frame posting a message that claims another case | rejected by the shell's `event.origin` check |
| `fetch` POST with JSON from the frame to the shell's settings endpoint | blocked, 0 accepted |
| `localStorage` inside the frame | works |
| Cookie set by the frame's own server, `SameSite=Lax` (the browsers' default) | **never sent** on the frame's next request |
| Cookie `SameSite=None; Secure` | sent in Chrome, Edge, Firefox, the VS Code browser; **not sent in Safari** |

- The frame on `<slug>.localhost` is cross-site to the shell. Serving the shell from
  `localhost` or from `review.localhost` instead of `127.0.0.1` does not change that:
  every `*.localhost` name is a site of its own (checked in Chrome).
- Safari sends no cookies at all to the cross-site frame.

**Consequence:** a page that needs a login cookie, which in practice means a dev server
with a session, will not stay logged in inside the review frame. Static files and dev
servers without a login are unaffected. This is inherent to giving each review its own
origin, which is what keeps the reviewed page away from the shell. It is recorded as a
limit for 1.2, not worked around.

## Q3. A Vite dev server through the proxy

Vite 8.3.0, vanilla template.

| Check | Result (Chrome, VS Code browser) |
|---|---|
| Vite's Host check | passes; the proxy sends the target's own Host |
| Hot reload WebSocket | goes through the proxy (the proxy's upgrade count rose on each load) |
| CSS edit | the frame's colour changed with no reload; the probe kept running (same run counter) |
| JS edit | full reload; the probe was injected again exactly once (run counter +1) |
| The same page opened directly in a tab, through the proxy | reloaded on the JS edit as well |

**Chosen for Phase 5:** forward requests with the target's Host, strip
`Accept-Encoding` so HTML can be rewritten, and pipe WebSocket upgrades through as raw
bytes. Nothing Vite-specific was needed.

## Q4. The probe under a strict CSP

| Policy | Probe ran | The page's own scripts |
|---|---|---|
| Header `script-src 'self'; frame-ancestors 'none'`, plus `X-Frame-Options: DENY` declared | yes, frame loaded (both frame blockers stripped) | n/a |
| Header `script-src 'nonce-…' 'strict-dynamic'` | yes | n/a |
| `<meta http-equiv="Content-Security-Policy">` with a nonce and `strict-dynamic` | yes | yes, the page's own nonce script still ran |

Same in every browser above.

- The probe is an external script from the frame's own origin, so `'self'` covers it.
  For nonce-only policies the server generated a fresh nonce per response, added
  `'nonce-<ours>'` to `script-src` (or `default-src`) in the header and in any `<meta>`
  policy, and put the same nonce on the probe's `<script>` tag. That worked everywhere.
- A hash source was not tried. It would need an `integrity` attribute on the external
  script, and the nonce already works.
- The probe tag sits right after `<head>`, so it comes before any `<meta>` policy. The
  rewrite still matters, because the probe's later requests fall under that policy.
- A first, buggy regex for the `<meta>` rewrite stopped at the first quote inside the
  policy and broke the page's own nonce. Match the attribute by its own quote character.

**Chosen for Phase 1: the nonce rewrite, in the header and in `<meta>`, not a hash.**
