# -*- coding: utf-8 -*-
"""Files around the plugin that a release depends on: workflows and release script."""
import io
import os

from harness import test, HERE

REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))


def read(rel):
    with io.open(os.path.join(REPO, *rel.split("/")), encoding="utf-8") as fh:
        return fh.read()


@test
def test_ci_runs_everything_on_three_systems():
    wf = read(".github/workflows/test.yml")
    for needle in ("windows-latest", "macos-latest", "ubuntu-latest", '"3.10"', '"3.13"',
                   "pull_request", "python plugins/review-doc/tests/run.py",
                   "actions/setup-node", "fail-fast: false"):
        assert needle in wf, needle
    assert "npx --yes @vscode/vsce package -o review-doc-opener.vsix" in wf, \
        "every push proves the opener still packages"


def release_notes():
    import importlib.util
    path = os.path.join(REPO, ".github", "scripts", "release_notes.py")
    spec = importlib.util.spec_from_file_location("release_notes", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LOG = """# Changelog

## [Unreleased]

## [1.0.1] - 2026-10-09

### Fixed
- B.

## [1.0.0] - 2026-10-02

### Added
- A.
"""


@test
def test_release_notes_extract_the_version_section():
    rn = release_notes()
    assert rn.section(LOG, "1.0.0") == "### Added\n- A."
    assert rn.section(LOG, "1.0.1") == "### Fixed\n- B."


@test
def test_release_notes_refuse_a_tag_that_is_not_the_version():
    """Review Focus 3: no release may point the offer at a missing asset."""
    import contextlib
    rn = release_notes()
    try:
        rn.section(LOG, "2.0.0")
        raise AssertionError("a missing section must raise")
    except ValueError:
        pass
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert rn.main(["v9.9.9"], version="1.0.0", changelog=LOG) == 1
        assert rn.main(["1.0.0"], version="1.0.0", changelog=LOG) == 1, "the tag needs its v"
        assert rn.main(["v1.0.0"], version="1.0.0", changelog=LOG) == 0


@test
def test_release_workflow_builds_and_attaches_the_opener():
    import extension
    wf = read(".github/workflows/release.yml")
    for needle in ('tags: ["v*"]', "contents: write",
                   "python .github/scripts/release_notes.py \"$GITHUB_REF_NAME\" > notes.md",
                   "npx --yes @vscode/vsce package -o review-doc-opener.vsix",
                   "plugins/review-doc/vscode-opener/review-doc-opener.vsix",
                   "gh release create", "--notes-file notes.md"):
        assert needle in wf, needle
    assert extension.RELEASE_URL.endswith("/v%s/review-doc-opener.vsix"), extension.RELEASE_URL
    assert wf.index("release_notes.py") < wf.index("vsce package"), "check the tag before building"
