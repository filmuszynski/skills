# ADR 0020: HTML review ships proofreading first; a local address leads to its file

**Status:** Accepted (24.10.2026).

## Context

HTML review was planned as one release with two jobs: proofreading the text of a
finished page, and design feedback on a page that is still being built, served by a
dev server through a proxy (ADR 0018 was reserved for that proxy). The two need very
different machinery. Proofreading needs the frame origin (ADR 0016), the probe (ADR
0017) and the anchor backend (ADR 0019). Design feedback also needs a proxy that
rewrites another server's responses, hot reload and pages that are not files at all.

Most HTML pages people want reviewed are files: a report built by a script, a page
saved from a tool, a static site. People often look at them through a small static
server, such as `python -m http.server`, and hand over the address they see in the
browser rather than the file.

## Decision

1. **1.2.0 is proofreading.** Comments on selected text, rewrites in place, rounds,
   the lost-items strip and the answer, for a local `.html` or `.htm` file served from
   its own folder. Design feedback and dev servers move to 1.3.0, and ADR 0018 stays
   reserved for the proxy.
2. **A local address leads to its file.** When `/vet` is given an `http://` or
   `https://` address on `localhost`, `127.0.0.1` or `[::1]`, Claude finds the process
   listening on the port and the folder it serves (`--directory`, else its working
   directory, else a search of the project for the file's name), maps the address's
   path to a file and checks it is the served page:
   the same bytes, or the same `<title>` with no other candidate. Then it renders that
   file. When the check fails, Claude says what it found and asks for the path.
3. **The renderer still refuses addresses** (exit 4). Finding the file is Claude's
   job, written down in the `review-html` skill, so the renderer never guesses.
4. Any other address is declined: "HTML review opens local files and localhost only."
   A dev server is told: "Reviewing a dev server arrives in 1.3."

## Consequences

- A page served from a folder reviews exactly like the file, with the same link.
- The lookup needs the operating system's own tools (`Get-NetTCPConnection` on
  Windows, `lsof` on macOS and Linux). Windows does not show a process's working
  directory, so there a server started without `--directory` is found by searching the
  project for the file's name; the byte check keeps a wrong hit out. Where nothing
  matches, Claude asks for the path.
- Pages built by a generator are reviewed as output, and the answer is applied to the
  generator's source. The skill says so, because editing the output would be lost on
  the next build.
- 1.3.0 can add the proxy without changing how files are reviewed.

## Alternatives

- **Build the proxy first, then ship both.** Rejected: it delays proofreading, which
  covers most real pages, behind the hardest part.
- **Refuse every address.** Rejected: the user would have to find the file by hand
  each time, for a lookup Claude can do and check in a few commands.
- **Teach the renderer to resolve addresses.** Rejected: process lookup differs by
  system and needs judgement when it is ambiguous; a skill can ask, a script cannot.
