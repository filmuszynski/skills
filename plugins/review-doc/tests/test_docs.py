# -*- coding: utf-8 -*-
"""The public documentation says what the plugin really does, in the spec's order."""
import io
import os
import re

from harness import test, HERE

import settings

REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SECTIONS = ["What it does", "Install", "First use", "Plan review", "Settings",
            "Advanced: choice screens", "Troubleshooting", "Manual install",
            "Also in this repository: context-warning",
            "License and credit"]
SHOTS = ["page", "comment", "edit", "settings", "reload", "plan", "choice"]


def read(*parts):
    with io.open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


@test
def test_readme_follows_the_spec_order():
    heads = re.findall(r"^## (.+)$", read("README.md"), re.M)
    assert heads == SECTIONS, heads


@test
def test_readme_names_the_real_commands_and_settings():
    text = read("README.md")
    for needle in ("/plugin marketplace add filmuszynski/skills",
                   "/plugin install review-doc@filmuszynski-skills", "/reload-plugins",
                   "/review-doc:review-doc", "/review-doc:settings", "Python 3.10",
                   "127.0.0.1", "7777", "TERM_PROGRAM", "server.log"):
        assert needle in text, needle
    for name in settings.CLI_NAMES:
        assert "`%s`" % name in text, name
    assert "—" not in text, "no em dashes"


@test
def test_screenshots_exist_and_the_readme_shows_them():
    text = read("README.md")
    linked = re.findall(r"\]\((docs/screenshots/[^)]+)\)", text)
    for rel in linked:
        assert os.path.isfile(os.path.join(REPO, rel)), rel
    for name in SHOTS:
        path = os.path.join(REPO, "docs", "screenshots", name + ".png")
        with open(path, "rb") as fh:
            assert fh.read(8) == b"\x89PNG\r\n\x1a\n", name
        assert "docs/screenshots/%s.png" % name in linked, name


@test
def test_contributing_and_issue_templates():
    c = read("CONTRIBUTING.md")
    for needle in ("python plugins/review-doc/tests/run.py", "Python 3.10", "node", "bash",
                   "CHANGELOG.md", "[Unreleased]", "docs/screenshots/make.py"):
        assert needle in c, needle
    for name in ("bug_report.md", "feature_request.md"):
        t = read(".github", "ISSUE_TEMPLATE", name)
        assert t.startswith("---\nname: "), name
    bug = read(".github", "ISSUE_TEMPLATE", "bug_report.md")
    for needle in ("Operating system", "Python version", "review-doc version", "server.log"):
        assert needle in bug, needle
