# -*- coding: utf-8 -*-
"""The HTML page kind: its layout, its script, and the html CLI kind (1.2)."""
import json
import os
import subprocess

from harness import test, new_home, HERE, fixture

import layout_doc
import layout_html
import pages
import shell


def _fixture_path(name):
    return os.path.join(HERE, "fixtures", name)


@test
def test_layout_builds_a_frame_page():
    src = _fixture_path("site_single.html").replace("\\", "/")
    built = layout_html.build(fixture("site_single.html"), source=src,
                              slug="fixtures-site-single-1a2b3c", generated_at="2026-10-02T10:00:00")
    assert built["title"] == "Single page fixture"
    assert built["sections"] == []
    assert built["meta"]["kind"] == "html" and built["meta"]["slug"] == "fixtures-site-single-1a2b3c"
    assert built["meta"]["target"] == {"type": "file", "root": os.path.dirname(src), "entry": "site_single.html"}
    assert built["prompt_spec"]["header"] == 'Review of the HTML page "Single page fixture" (%s):' % src
    assert built["prompt_spec"]["generalLabel"] == "Whole page"
    assert built["scripts"] == ["shell_html.js"]
    assert '<iframe id="review-frame" title="Single page fixture"' in built["body_html"]


@test
def test_title_falls_back_to_the_file_name():
    assert layout_html.page_title("<p>no title</p>", "index.html") == "index.html"
    assert layout_html.page_title("<TITLE>  A &amp; B\n </TITLE>", "x") == "A & B"
    assert layout_html.page_title("<title></title>", "x.html") == "x.html"


@test
def test_html_verdicts_name_the_page():
    assert [a["verdict"] for a in layout_html.ACTIONS] == ["approve", "changes"]
    words = " ".join(a.get(k, "") for a in layout_html.ACTIONS for k in ("line", "bare", "tip"))
    assert "document" not in words and "The page is finished." in words, words
    assert layout_doc.ACTIONS[0]["bare"] == "VERDICT: approved. The document is finished.", \
        "the document page keeps its own words"


@test
def test_rendered_html_page_loads_shell_html_in_its_own_script_block():
    h = new_home()
    built = layout_html.build(fixture("site_single.html"), source="/x/site_single.html", slug="x-site-single-1a2b3c")
    html = shell.render(**built)
    # A separate block: an error in shell.js must not stop the frame from loading.
    assert "</script>\n<script>\n/* review-doc: the shell side of an HTML page" in html
    assert '<span class="eyebrow" data-kind="html">HTML</span>' in html
    meta = pages.read_meta(shell.write(os.path.join(h, "pages", "x-site-single-1a2b3c.html"), html))
    assert meta["kind"] == "html" and meta["target"]["entry"] == "site_single.html"


@test
def test_other_pages_do_not_load_shell_html():
    built = layout_doc.build("# T\n\n## A\n\nx\n", source="/x/n.md", slug="n")
    assert "function frameSrc(" not in shell.render(**built)


def _frame_src(meta, loc):
    js = shell._asset("shell_html.js")
    start = js.index("function frameSrc(")
    depth, i = 0, js.index("{", start)
    while True:
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    src = js[start:i + 1] + "\nprocess.stdout.write(JSON.stringify(frameSrc(%s, %s)));" % (
        json.dumps(meta), json.dumps(loc))
    out = subprocess.run(["node", "-e", src], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    return json.loads(out.stdout.decode("utf-8"))


@test
def test_frame_src_is_the_slug_origin_on_port_plus_100():
    meta = {"slug": "x-site-1a2b3c", "target": {"type": "file", "root": "/x", "entry": "my page.html"}}
    assert _frame_src(meta, {"protocol": "http:", "port": "7777"}) == \
        "http://x-site-1a2b3c.localhost:7877/my%20page.html"
    assert _frame_src(meta, {"protocol": "file:", "port": ""}) == ""
    assert _frame_src({"slug": "s", "target": {"type": "proxy"}}, {"protocol": "http:", "port": "7777"}) == ""


@test
def test_a_hostile_title_is_not_rescanned_for_placeholders():
    h = new_home()
    raw = '<title>__ACTIONS__ __BODY__ __JS__ <b>"x"</b></title>'
    built = layout_html.build(raw, source="/x/t.html", slug="x-t-1a2b3c")
    html = shell.render(**built)
    meta = pages.read_meta(shell.write(os.path.join(h, "pages", "x-t-1a2b3c.html"), html))
    assert meta["kind"] == "html" and meta["slug"] == "x-t-1a2b3c"
    assert 'title="__ACTIONS__ __BODY__ __JS__ &lt;b&gt;&quot;x&quot;&lt;/b&gt;"' in html
    assert html.count('<button class="chip verdict ') == len(layout_html.ACTIONS)
    assert html.count("/* Presenter shell behaviour.") == 1


@test
def test_page_words_respect_word_boundaries():
    assert layout_html._page_words("the document and documents; documentation") == \
        "the page and pages; documentation"


@test
def test_doc_page_render_is_unchanged_by_the_single_pass():
    built = layout_doc.build("# T\n\n## A\n\nx\n", source="/x/n.md", slug="n")
    new = shell.render(**built)
    # The old way: one chained replace per placeholder.
    meta = built["meta"]
    kind = meta.get("kind", "document")
    old = shell.PAGE
    old = old.replace("__CREDIT__", shell._credit_html(meta.get("version")))
    old = old.replace("__CSS__", shell._asset("shell.css"))
    data = {"sections": list(built["sections"]),
            "prompt": {"header": built["prompt_spec"].get("header", "Feedback:"),
                       "footer": built["prompt_spec"].get("footer", ""),
                       "generalLabel": built["prompt_spec"].get("generalLabel", "Whole plan")},
            "meta": dict(meta),
            "actions": built["actions"] if built.get("actions") is not None else shell.PLAN_ACTIONS,
            "select": built.get("select") or "one"}
    old = old.replace("__DATA__", shell._json_literal(data))
    old = old.replace("__JS__", shell._asset("shell.js"))
    old = old.replace("__BODY__", built["body_html"])
    old = old.replace("__ACTIONS__", shell._actions_html(data["actions"]))
    old = old.replace("__GENERAL__", shell._esc(built.get("general_placeholder") or "A note on the whole plan, optional"))
    old = old.replace("__PILL__", shell._esc(shell.PILL_KIND.get(kind, "")))
    old = old.replace("__KIND__", shell._esc(shell.EYEBROW_LABEL.get(kind, kind)))
    old = old.replace("__SHORT__", shell._esc(shell.short_title(built["title"], cap=400)))
    old = old.replace("__TITLE__", shell._esc(built["title"]))
    assert new == old
