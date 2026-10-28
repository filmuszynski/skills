# Phone review over Tailscale, Phase 0 findings (28.10.2026)

The throwaway spike for review pages on the phone. The review server ran from a spike
branch with its own home folder and ports, `tailscale serve` put it on the tailnet
(tailnet only, never Funnel), and the pages were opened in the Claude app on an Android
phone that steered the session through Remote Control. The spike code lived on a branch
that was deleted afterwards. Only this file remains.

Placeholders: `<machine>.<tailnet>.ts.net` is the computer's tailnet name, `<login>` the
tailnet owner's login.

Observed on Windows 11 with Tailscale 1.102.4, an Android phone with the Claude app, and
desktop Chrome on the same computer reaching the tailnet address. macOS and iOS were not
tested (no Mac at hand).

## Task 1. What arrives through `tailscale serve`

A header echo behind `tailscale serve --bg --https=8443 <port>`, opened from the
computer itself and from the phone.

| Header | Value |
|---|---|
| `Host` | `<machine>.<tailnet>.ts.net:8443` (the port is included) |
| `X-Forwarded-Proto` | `https` |
| `X-Forwarded-For` | the client's `100.x` tailnet address |
| `Tailscale-User-Login` | `<login>`, from the phone **and** from the computer itself |
| client address seen by the server | always `127.0.0.1` |

- The login header arrives for the owner's own devices, the computer included, so a
  check on it does not lock the owner out at the computer.
- The client address is useless for any check: `tailscale serve` connects from loopback.
- A non-default HTTPS port (8443) works; the user's own config on 443 can stay as it is.
- A link tapped in a Claude app chat opens inside the app (an in-app browser, a Chrome
  WebView user agent).

**For the build:** accept the tailnet Host only together with a matching
`Tailscale-User-Login`; never trust the client address.

## Task 2. The real review server on the phone (Markdown page)

The spike server accepted the tailnet Host and an `https://` Origin for writes.

| Check | Result |
|---|---|
| Page loads, comments and rewrites in the bubble | yes |
| Request changes, copy the answer, paste it through Remote Control | yes, two rounds |
| Reload strip after the source changed on the computer | yes |
| The open page reloads itself after a re-render | yes |
| Settings save | server path works (checked with a request over the tailnet); not possible from the phone, see below |

Phone layout bugs, none of them caused by Tailscale:

- **Selecting text with a finger does not open the comment bubble**, on Markdown and HTML
  pages alike.
- **Tapping into the comment box or a Settings field closes it at once.** Cause:
  `shell.js` closes every bubble on window `resize` and document `scroll`. The on-screen
  keyboard resizes the viewport and scrolls the field into view.
- The comment box and the Settings panel are cut off on the right. They should be
  centred on a narrow screen. Save was only reachable by swiping sideways.
- Overscroll at the bottom of the page, or a swipe on the bottom panel, scrolls the
  bottom panel up.

**For the build:** a phone layout phase of its own (see the roadmap). Marks stay per
origin, so marks made on the phone stay on the phone. That is expected: one round
happens on one device.

## Task 3. HTML review over the tailnet

ADR 0016 frames every HTML page on `<slug>.localhost:<frame port>`. The phone cannot
resolve that name, and a tailnet gives one name per machine, not one per review.

**Way A, the frame on its own served HTTPS port.** `tailscale serve --https=8444
<frame port>`. The frame listener mapped Host `<machine>.<tailnet>.ts.net:8444` to the
one review currently opened from the tailnet. `frame-ancestors` also listed
`https://<machine>.<tailnet>.ts.net:8443`, and the shell and the probe accepted the
`https` origins.

| Check | Result |
|---|---|
| Site renders in the frame, CSS and images | yes (phone) |
| Root-absolute paths (`/css/site.css`, `/img/…`) | yes |
| Edit text | yes (phone) |
| A link inside the site navigates in the frame, away strip shows | yes (phone) |
| Frame script reads `parent.document` / `parent.localStorage` | blocked |
| Cookies | none; the review server sets none |
| Second review sees the first review's `localStorage` | **yes, without a fix** |
| … with `Clear-Site-Data: "storage"` when the tailnet review changes | no, both start empty |
| The shell's own storage on :8443 after that clear | kept |

The storage checks ran in desktop Chrome over the tailnet, not on the phone; repeat them
on the phone in the HTML phase.

- Shell (:8443) and frame (:8444) are cross-origin but same-site. Cookies would cross
  between them, which is harmless only while the server sets none.
- One origin for every tailnet review means one review at a time. Opening the next one
  must clear the frame origin's storage, and an older shell whose frame was taken over
  must say so instead of showing someone else's page. The spike once showed a stale page
  from the browser cache after a switch, so the review must be part of the frame URL
  (for example a first request that names the slug, sets the current review, clears
  storage and redirects to the entry), not only server state.

**Way B, Tailscale Services** (`tailscale serve --service=svc:<name>`, a name of its own
per service): refused with "Service hosts must be tagged nodes". A tagged node is owned
by a tag instead of the user, and the service has to be defined in the admin console.
Too heavy to ask of every user. Not pursued.

**Chosen: Way A**, with `Clear-Site-Data` on every switch and the review named in the
frame URL. It keeps both ADR 0016 rules (no shared storage between reviews; the page's
scripts cannot reach the shell) at the cost of one HTML review at a time on the phone.
It gets a new ADR next to 0016.

## Task 3a. Can the page open on the phone by itself?

| Way | Result |
|---|---|
| A tool that opens a URL on the phone | none exists |
| Sending the page as a file to the phone | a card that needs a tap; inside it scripts run but the frame is blocked and no request reaches the computer (sandboxed static copy) |
| Push notification with the link | suppressed while the terminal has focus ("this terminal is active"); sent once the window lost focus, but nothing arrived on the Android phone, which matches an open community report. A tap would still be needed |
| **A page already open in the Claude app's in-app browser** | **works**: it keeps running while the user is in the chat, and navigated itself to a new review; on return the new page was showing |

- The in-app page survives switching to the chat and back, at the same scroll position.
- A small start page polled the server every 2 s, also while the chat was in front, and
  jumped as soon as a new address was set.

**For the build:** one tap per session. The handover's phone link opens the page; from
then on the open page follows the newest handover (the server records it, open pages
poll for it the way the Reload strip already polls, and navigate). A start page that only
waits is the same mechanism with no review in it. No push needed.

## Task 4. macOS and iOS

Not done: no Mac available. Still open: which Tailscale CLI the macOS App Store build
offers (`tailscale serve` from the standalone build vs the App Store one), the identity
header on macOS, and the in-app browser on iOS (does it keep running in the background,
and does the clipboard copy work). Check on a Mac before the release.
