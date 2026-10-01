# -*- coding: utf-8 -*-
"""Fixes from the Phase 2 final review."""
import contextlib
import io
import json
import os
import threading

from harness import test, new_home, use_home, env, patch
from serverkit import serving, review_server

import build_screen
import launch
import layout_doc
import layout_plan
import settings
import shell


def held_open(path, seconds=0.4):
    """Keep path open for reading for a while, as the server does while serving it.
    On Windows that blocks os.replace onto path until the reader closes."""
    fh = open(path, "rb")
    threading.Timer(seconds, fh.close).start()


@test
def test_page_write_waits_for_a_reader():
    h = new_home()
    target = os.path.join(h, "page.html")
    shell.write(target, "old")
    held_open(target)
    shell.write(target, "new")
    assert io.open(target, encoding="utf-8").read() == "new"


@test
def test_server_json_write_waits_for_a_reader():
    h = new_home()
    target = os.path.join(h, "server.json")
    review_server._write_json(target, {"port": 1})
    held_open(target)
    review_server._write_json(target, {"port": 2})
    assert json.load(io.open(target, encoding="utf-8")) == {"port": 2}


@test
def test_settings_save_waits_for_a_slow_reader():
    h = new_home()
    settings.set_value("stale-hours", "10", h)
    held_open(os.path.join(h, "config.json"))
    assert settings.set_value("stale-hours", "20", h)["stale_hours"] == 20


@test
def test_main_reports_os_errors_as_json():
    h = use_home(new_home())
    s = os.path.join(h, "a.md")
    io.open(s, "w", encoding="utf-8").write("# A\n")

    def denied(path, html):
        raise PermissionError(13, "Access is denied", path)
    out = io.StringIO()
    with patch(shell, "write", denied), contextlib.redirect_stdout(out):
        code = build_screen.main(["doc", s])
    res = json.loads(out.getvalue())
    assert code == 1 and res["ok"] is False and "denied" in res["error"], res


@test
def test_server_main_logs_a_crash():
    h = use_home(new_home())

    def broken(self):
        raise OSError("disk on fire")
    with patch(review_server.ReviewServer, "start", broken):
        code = review_server.main()
    assert code == 1
    log = io.open(os.path.join(h, "server.log"), encoding="utf-8").read()
    assert "disk on fire" in log, log


@test
def test_newer_server_is_used_not_replaced():
    h = use_home(new_home())

    def boom(home=None):
        raise AssertionError("spawned over a newer server")
    with serving(h, version="99.0.0") as newer:
        with env(REVIEW_DOC_NO_SERVER=None), patch(launch, "spawn", boom):
            port, why = launch.ensure_server(h)
        assert port == newer.port, why
        assert not newer.stopping.is_set()


@test
def test_version_order():
    k = launch.version_key
    assert k("0.1.0-dev") < k("0.1.0") < k("0.1.1") < k("1.0.0") < k("1.10.0")
    assert k("0.0.1-old") < k("0.1.0-dev")
    assert k("garbage") < k("0.0.1")


@test
def test_paste_back_tells_claude_to_render_again_with_review_doc():
    """The answer a page copies must name a step any Claude can take, not a private path."""
    import layout_doc
    import layout_plan
    plan = layout_plan.build("# P\n\n### Task 1: A\n\n- [ ] **Step 1: x**\n", source="/x/p.md")
    doc = layout_doc.build("# T\n\n## A\n\nx\n", source="/x/t.md")
    for built in (plan, doc):
        footer = built["prompt_spec"]["footer"]
        assert "build_screen.py" not in footer, footer
        assert "render its review page again with review-doc" in footer, footer
        assert "/x/" in footer, "the source file is still named"


@test
def test_plan_header_fields_keep_their_wrapped_lines():
    import layout_plan
    raw = ("# P\n\n> **For agentic workers:** use a skill.\n\n"
           "**Goal:** first line\nsecond line\nthird line.\n\n"
           "**Architecture:** one line only.\n"
           "**Tech Stack:** Python.\n\n### Task 1: A\n\n- [ ] **Step 1: x**\n")
    meta = layout_plan.parse(raw)["meta"]
    assert " ".join(meta["Goal"].split()) == "first line second line third line.", meta
    assert meta["Architecture"] == "one line only.", meta
    assert meta["Tech Stack"] == "Python.", meta
    assert not any("agentic" in v for v in meta.values()), meta


@test
def test_plan_footer_names_the_marker_the_page_writes():
    """The page writes 'DECLINE the step'; a footer about SKIP leaves Claude guessing."""
    import io as _io
    import layout_plan
    from harness import PRESENTER
    plan = layout_plan.build("# P\n\n### Task 1: A\n\n- [ ] **Step 1: x**\n", source="/x/p.md")
    footer = plan["prompt_spec"]["footer"]
    js = _io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert 'DECLINE the step' in js
    assert "SKIP" not in footer and "DECLINE" in footer, footer


# ---------------------------------------------------------------- plan header
#
# The rule since 1.0.2: every line before the first section belongs to the field
# above it, in source order, until the next **Field:** line. Text before the first
# field sits above the table. Only the writing-plans banner is left out. Nothing is
# guessed, so nothing can be dropped or moved away from the line that introduces it.

import re as _re


def _words(text):
    return _re.findall(r"\w+", text, _re.UNICODE)


def _glance_words(raw):
    import layout_plan
    import html as _html
    out = layout_plan._meta_html(layout_plan.parse(raw))
    out = out.split("<h2>At a glance</h2>", 1)[1] if out else ""
    return _words(_html.unescape(_re.sub(r"<[^>]+>", " ", out)))


def _header_words(raw):
    """The words of the header as written: after the title, before the first
    section, without the banner."""
    if raw.startswith("# ") or "\n# " in raw:
        head = raw.split("\n# ", 1)[-1] if not raw.startswith("# ") else raw[2:]
        head = head.split("\n", 1)[1] if "\n" in head else ""
    else:
        head = raw            # no title: the whole top of the file is header
    head = _re.split(r"\n(?:## |### Task )", "\n" + head, maxsplit=1)[0]
    lines, banner = [], False
    for line in head.split("\n"):
        if line.startswith("> **For agentic workers:**"):
            banner = True
        if banner and line.startswith(">"):
            continue
        banner = False
        # A fence's language tag (```bash) names the code; it is never shown.
        lines.append(_re.sub(r"^(\s*(?:```|~~~))\S+", r"\1", line))
    return _words("\n".join(lines))


HEADERS = {
    "quote under a field": (
        "# P\n\n**Request:** in 1.0.0 it vanished from the page:\n\n"
        "> - first point\n> - second point\n\n"
        "**Where to look:** the pill.\n\n### Task 1: A\n\n- [ ] **Step 1: x**\n"),
    "list, fence, table, rule": (
        "# P\n\n**Goal:** one line\n- a list line\n1. numbered\n\n```python\ncode = 1\n```\n\n"
        "| a | b |\n|---|---|\n| c | d |\n\nmiddle\n\n---\n\nafter the rule\n\n"
        "**Repo:** r.\n\n## Context\n\nx\n"),
    "prose before and between fields": (
        "<!-- generated file -->\n\n# P\n\n> **For agentic workers:** use a skill.\n"
        "> Second banner line.\n\nA lead paragraph.\n\n**Goal:** g\nwrapped on\n2026. a date line\n\n"
        "A paragraph between the fields.\n\n**Repo:** r.\n\n---\n\n### Task 1: A\n\n- [ ] **Step 1: x**\n"),
    "no title": "**Goal:** g.\n**Repo:** r.\n\n## Context\n\nx\n",
    "rule straight under a field": "# P\n\n**Goal:** a\n---\nmore\n\n**Repo:** b\n===\n\n## C\n\nx\n",
    "mixed fences": ("# P\n\n**Goal:** g\n~~~\n```\n~~~\n\n````\n```\n**Not:** a field\n````\n\n"
                     "**Repo:** r ünïcødé Ωμέγα 漢字\n\n### Task 1: A\n\n- [ ] **Step 1: x**\n"),
}


@test
def test_plan_header_structure_holds():
    """Words in order are not enough: no field may turn into a heading, swallow a
    section, or grow a field that is not one."""
    import layout_plan
    want = {"quote under a field": ["Request", "Where to look"],
            "no title": ["Goal", "Repo"],
            "rule straight under a field": ["Goal", "Repo"],
            "mixed fences": ["Goal", "Repo"]}
    for name, fields in want.items():
        plan = layout_plan.parse(HEADERS[name])
        assert list(plan["meta"]) == fields, (name, list(plan["meta"]))
        html = layout_plan._meta_html(plan)
        for cell in html.split("<td>")[1:]:
            assert not _re.search(r"<h[1-6]", cell.split("</td>")[0]), (name, cell[:120])
        assert plan["sections"], (name, "the first section survives")
    mixed = layout_plan.parse(HEADERS["mixed fences"])
    assert [s["num"] for s in mixed["sections"]] == ["Task 1"]
    assert "**Not:** a field" in mixed["meta"]["Goal"], "a field line inside a fence is code"


@test
def test_plan_header_unclosed_fence_does_not_swallow_the_plan():
    import layout_plan
    plan = layout_plan.parse("# P\n\n**Goal:** g\n```\nhalf a block\n\n### Task 1: A\n\n- [ ] **Step 1: x**\n")
    assert [s["num"] for s in plan["sections"]] == ["Task 1"], plan["sections"]
    assert "half a block" in plan["meta"]["Goal"]


@test
def test_plan_header_never_drops_or_reorders_text():
    """Every word of the header reaches At a glance, once, in the order written."""
    for name, raw in HEADERS.items():
        assert _glance_words(raw) == _header_words(raw), (name, _glance_words(raw), _header_words(raw))


@test
def test_plan_header_fixtures_keep_every_word():
    import glob
    from harness import HERE
    files = glob.glob(os.path.join(HERE, "fixtures", "plan_*.md"))
    assert files
    for f in files:
        raw = io.open(f, encoding="utf-8-sig").read()
        assert _glance_words(raw) == _header_words(raw), os.path.basename(f)


@test
def test_plan_header_block_stays_in_its_fields_row():
    """Filip, 01.10.2026, twice: the quote under a field read as cut off."""
    import layout_plan
    html = layout_plan._meta_html(layout_plan.parse(HEADERS["quote under a field"]))
    rows = html.split("<tr>")[1:]
    request = [r for r in rows if "<th>Request</th>" in r][0]
    assert "vanished from the page:" in request and "first point" in request and "second point" in request
    assert "<blockquote>" in request, "the quote keeps its Markdown"
    where = [r for r in rows if "<th>Where to look</th>" in r][0]
    assert "first point" not in where


@test
def test_plan_header_wrapped_value_is_one_line_of_text():
    import layout_plan
    html = layout_plan._meta_html(layout_plan.parse(
        "# P\n\n**Goal:** first line\nsecond line.\n\n### Task 1: A\n"))
    cell = html.split("<td>", 1)[1].split("</td>", 1)[0]
    assert cell.strip() == "first line\nsecond line.", repr(cell)


@test
def test_plan_header_lead_text_sits_above_the_table():
    import layout_plan
    html = layout_plan._meta_html(layout_plan.parse(HEADERS["prose before and between fields"]))
    assert html.index("A lead paragraph.") < html.index("<table>")
    assert "agentic" not in html and "banner" not in html and "generated" not in html


@test
def test_plan_header_closing_rule_is_not_shown():
    """The --- that closes a plan's header frames it; it is not content."""
    import layout_plan
    plan = layout_plan.parse("# P\n\n**Goal:** g.\n\n---\n\n## Context\n\nx\n")
    assert plan["meta"]["Goal"] == "g.", repr(plan["meta"]["Goal"])
    assert "<hr" not in layout_plan._meta_html(plan)


@test
def test_plan_without_header_text_renders_no_notes():
    import layout_plan
    plan = layout_plan.parse("# P\n\n**Goal:** g.\n\n### Task 1: A\n\n- [ ] **Step 1: x**\n")
    assert plan["preamble"] == ""
    html = layout_plan._meta_html(plan)
    assert "glance-notes" not in html and "<td>g.</td>" in html



@test
def test_document_fields_get_the_glance_box_on_the_lead():
    md = ("# Spec\n\nIntro line.\n\n**Date:** 01.10.2026\n**Status:** draft\n"
          "> quoted under status\n\n## One\n\nText.\n")
    built = layout_doc.build(md, source="/x/spec.md")
    html = built["body_html"]
    lead_id = built["sections"][0]["id"]
    assert built["sections"][0]["kind"] == "intro"
    assert 'class="sec lead glance" data-sec="%s"' % lead_id in html
    box = html[html.index("glance"):html.index("</table>")]
    assert "<h2>At a glance</h2>" in box and "Intro line." in box
    assert "<th>Date</th>" in box and "01.10.2026" in box
    assert box.index("draft") < box.index("quoted under status"), "the quote stays in its field"
    assert "data-edit-id" in box, "field values are rewritable"


@test
def test_document_without_fields_renders_as_before():
    md = "# Doc\n\nJust a lead.\n\n## A\n\nText.\n"
    html = layout_doc.build(md, source="/x/d.md")["body_html"]
    assert "glance" not in html and "Just a lead." in html


@test
def test_plan_header_still_uses_the_shared_parser():
    p = layout_plan.parse("# P\n\n**Goal:** g\n- a\n- b\n\n## S\n\nx\n")
    assert p["meta"]["Goal"].startswith("g") and "- a" in p["meta"]["Goal"]
    assert hasattr(layout_plan, "header_blocks")


@test
def test_glance_css_covers_documents():
    css = shell._asset("shell.css")
    assert '.sec[data-sec="__meta"],\n.sec.glance,' in css
