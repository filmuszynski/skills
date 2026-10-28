# Roadmap: review-doc

Phased so the riskiest unknowns are proven first. Each phase gets its own approved plan before
any code; plans stay in the author's private workspace (ADR 0008).

| Phase | What | Done when |
|---|---|---|
| 0 ✅ | Scaffold + spike (done 30.09.2026, see `docs/spikes/`): plugin hooks and Python on Windows, detached server from a hook, marketplace install from a private GitHub repo, plugin command naming, how skills find their own files | Findings report written, ADRs updated, spike code deleted |
| 1 ✅ | Port the presenter into the plugin: neutral fixtures, vendored markdown, `~/.review-doc/`, hashed slugs, absolute `meta.source`, `meta.version`, MD label, kind switches, `settings.py` + CLI (done 30.09.2026) | All ported and new tests green |
| 2 ✅ | Server: `review_server.py`, auto-start, endpoints, Host check, pruning, rebuild on request, auto-open (done 30.09.2026, ADR 0011) | Server tests green; manual check of start, rebuild, prune |
| 3 ✅ | Page: credit line, settings panel, mark expiry from settings (done 30.09.2026, ADR 0012) | Tests green; browser check |
| 4 ✅ | Skills, commands, Python plan hook, VS Code extension renamed and hardened, first-use offer (done 01.10.2026, ADR 0013) | Local plugin install works end to end |
| 5 ✅ | README, CHANGELOG, CONTRIBUTING, issue templates, screenshots, CI on three systems, privacy sweep, v1.0.0 release (done 01.10.2026, ADR 0014) | Repo public after Filip's go; release published |
| 6 ✅ | Filip's switch-over from the private presenter (done 01.10.2026) | Private copy removed; CLAUDE.md, MANIFEST, memory updated |

## 1.2.0: HTML review (proofreading)

| Phase | What | Done when |
|---|---|---|
| 0 ✅ | Spike: a page in a frame on its own origin, a probe inside it, postMessage both ways (ADR 0016, 0017) | Findings written |
| 1 ✅ | The frame listener, the `html` kind in the renderer, the frame page | Tests green |
| 2 ✅ | The anchor backend seam: marks, bubbles and counters through one interface (ADR 0019) | Tests green; md pages unchanged |
| 3 ✅ | Use, Comment and Edit text on the page: the probe draws, comments on selected text, rewrites in place | Tests green; browser check |
| 4 ✅ | The answer, the four-step lookup, the lost-items strip, rounds, reload | Tests green; browser check |
| 5 | Skills (`/vet` routes HTML, `review-html`), local addresses, charsets, the setting, docs, release (ADR 0020) | v1.2.0 released; one real round |

## Phone review over Tailscale (version not yet set)

Review pages opened in the Claude app on the phone, with the session steered through
Remote Control. Off by default (a `phone` setting); tailnet only, never Funnel.

| Phase | What | Done when |
|---|---|---|
| 0 ✅ | Spike (done 28.10.2026, see `docs/spikes/2026-10-28-phone-phase-0-findings.md`) | Findings written |
| 1 | `phone` setting (off by default) and recording the owner's login; the server accepts the tailnet Host and `https` Origin only with that `Tailscale-User-Login`; `tailscale serve` started with the server and stopped with it, on a free HTTPS port, never over an existing config | Tests green; phone round on a Markdown page |
| 2 | Phone link in every handover: renderer JSON field, `/vet` handover text, plan hook's `additionalContext`; the server records the newest handover and open pages follow it, so after one tap per session new pages open on the phone by themselves | Tests green; plan and doc pages hand over three lines and follow on the phone |
| 3 | Phone layout: touch selection opens the comment bubble; the on-screen keyboard no longer closes bubbles and Settings; bubbles and Settings centred on narrow screens; no overscroll of the bottom panel | Tests green; phone round with comments and a Settings save |
| 4 | HTML review over the tailnet: frame on its own served HTTPS port, one tailnet review at a time, review named in the frame URL, `Clear-Site-Data` on every switch; new ADR next to 0016 | Tests green; phone round on an HTML page, storage checks repeated on the phone |
| 5 | ADRs (tailnet Host, amending 0012), README, CHANGELOG, screenshots, release, the author's install; macOS and iOS checks | Released; checked on a Mac and an iPhone |
| 6 | Setup instructions for a second user (author's private workspace) | Approved by the author |

## Later

| Release | What |
|---|---|
| 1.3.0 | Design feedback and dev servers through a proxy (ADR 0018 reserved) |

Phase 0 findings that change later phases: single-instance lock (2), launcher chain and
skill-only parent entry point (4), `/reload-plugins` in the install guide and prefixed names (5).
