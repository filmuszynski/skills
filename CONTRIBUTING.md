# Contributing

Thank you for helping. Bug reports are the most useful thing you can send.

## Reporting a bug

Open an issue with the bug report template. It asks for your operating system, Python
version, the review-doc version (shown at the foot of every page) and the last lines
of `~/.review-doc/server.log`.

## Running the tests

You need Python 3.10 or later, `node` and `bash` (on Windows, Git Bash) on your PATH.
From the repository root:

    python plugins/review-doc/tests/run.py

The last line must read `… passed, 0 failed`. The tests never touch your real
`~/.review-doc/`, never start a server on ports 7777 to 7787 and never open a browser.
CI runs the same command on Windows, macOS and Linux for every push and pull request.

## Changing things

- Python standard library only. Third-party code is vendored with its license.
- Every hook exits 0, whatever happens.
- Add a line under `## [Unreleased]` in `CHANGELOG.md` for anything a user would notice.
- If you change how the page looks, retake the screenshots with
  `python docs/screenshots/make.py` (needs Chrome and Node 22 or later).
- Larger decisions get a short record in `docs/adr/`.
