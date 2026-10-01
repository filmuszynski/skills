# skills: working rules

Public repo `filmuszynski/skills`. Everything committed here is readable by anyone.

- Never commit customer names, paths from the author's private workspace, email addresses or tokens.
- `sessions/` and `.claude/settings.local.json` are gitignored on purpose. Do not un-ignore them.
- Python 3.10+, standard library only. Third-party code is vendored with its license.
- Every hook fails soft: exit 0 on any error.
- Version lives in `plugins/review-doc/.claude-plugin/plugin.json`. The footer and
  CHANGELOG must match it; a test enforces this.
- Each phase has an approved plan before code. Specs and plans are kept in the author's
  private workspace (ADR 0008), never in this repo. Decisions go in `docs/adr/`;
  supersede with a new ADR, never edit an accepted one.
- Tests: `python plugins/review-doc/tests/run.py`; CI runs them on three systems.
- `test_privacy.py` sweeps every file a `git add -A` would commit. Fix a hit at its
  source; never skip a whole file.
- Releases: bump `plugin.json`, the opener's `package.json` and the CHANGELOG together,
  then push the tag `v<version>`; `release.yml` does the rest.
- Screenshots: `python docs/screenshots/make.py` after any change to the page's look.
