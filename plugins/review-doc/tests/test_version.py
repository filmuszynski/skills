# -*- coding: utf-8 -*-
import io
import json
import os

from harness import test, HERE, new_home

import paths
import shell
import layout_doc
import layout_plan

REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))


def eyebrow(html):
    start = html.index('<span class="eyebrow"')
    start = html.index(">", start) + 1
    return html[start:html.index("</span>", start)]


def pill_kind(html):
    tag = html[html.index('<span class="eyebrow"'):]
    return tag.split('data-kind="', 1)[1].split('"', 1)[0]


@test
def test_doc_pages_say_md():
    built = layout_doc.build("# T\n\n## A\n\nx\n", source="/x/t.md")
    assert eyebrow(shell.render(**built)) == "MD"
    assert built["meta"]["kind"] == "doc"


@test
def test_plan_pages_keep_plan():
    built = layout_plan.build("# P\n\n### Task 1: A\n\n- [ ] **Step 1: x**\n", source="/x/p.md")
    assert eyebrow(shell.render(**built)) == "PLAN"


@test
def test_every_kind_wears_its_pill():
    doc = shell.render(**layout_doc.build("# T\n\n## A\n\nx\n", source="/x/t.md"))
    plan = shell.render(**layout_plan.build("# P\n\n### Task 1: A\n\n- [ ] **Step 1: x**\n", source="/x/p.md"))
    assert (eyebrow(doc), pill_kind(doc)) == ("MD", "md")
    assert (eyebrow(plan), pill_kind(plan)) == ("PLAN", "plan")
    for kind in ("options", "explain"):
        assert shell.EYEBROW_LABEL[kind] == "CHOICE" and shell.PILL_KIND[kind] == "choice"
    assert shell.EYEBROW_LABEL["html"] == "HTML" and shell.PILL_KIND["html"] == "html"


@test
def test_pill_sits_left_of_the_title():
    html = shell.render(**layout_doc.build("# T\n\n## A\n\nx\n", source="/x/t.md"))
    head = html.split("<header>", 1)[1]
    assert head.index('class="eyebrow"') < head.index('class="doc-title"')


@test
def test_unknown_kind_still_renders():
    built = layout_doc.build("# T\n\n## A\n\nx\n", source="/x/t.md")
    built["meta"]["kind"] = "future"
    html = shell.render(**built)
    assert eyebrow(html) == "future" and pill_kind(html) == ""


@test
def test_changelog_matches_version():
    v = paths.version()
    log = io.open(os.path.join(REPO, "CHANGELOG.md"), encoding="utf-8").read()
    if "-dev" in v:
        assert "## [Unreleased]" in log
    else:
        assert "## [%s]" % v in log, v


@test
def test_marketplace_lists_the_plugin_with_a_description():
    with io.open(os.path.join(REPO, ".claude-plugin", "marketplace.json"), encoding="utf-8") as fh:
        m = json.load(fh)
    assert m.get("description") and "SPIKE" not in json.dumps(m)
    assert [p["name"] for p in m["plugins"]] == ["review-doc", "context-warning"]


@test
def test_footer_shows_the_plugin_version():
    import build_screen
    h = new_home()
    src = os.path.join(h, "a.md")
    with io.open(src, "w", encoding="utf-8") as fh:
        fh.write("# A\n\n## B\n\nx\n")
    res = build_screen.build("doc", src, out_dir=h)
    with io.open(os.path.join(h, res["slug"] + ".html"), encoding="utf-8") as fh:
        html = fh.read()
    assert '<span class="credit-version">v.%s</span>' % paths.version() in html
