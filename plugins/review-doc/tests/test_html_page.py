# -*- coding: utf-8 -*-
"""The HTML page kind: its layout, its script, and the html CLI kind (1.2)."""
import contextlib
import io
import json
import os
import pathlib
import shutil
import subprocess

from harness import test, new_home, use_home, patch, HERE, fixture

import build_screen
import layout_doc
import layout_html
import pages
import settings
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


def _main_json(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = build_screen.main(argv)
    return code, json.loads(out.getvalue())


def _copy_single(home, name="index.html"):
    d = os.path.join(home, "site")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    shutil.copy(_fixture_path("site_single.html"), p)
    return p


@test
def test_build_html_writes_a_frame_page():
    h = use_home(new_home())
    p = _copy_single(h)
    res = build_screen.build("html", p)
    assert res["kind"] == "html" and res["new"] is True and res["sections"] == 0, res
    assert pages.HTML_SLUG_RE.match(res["slug"]) and res["slug"].startswith("site-index-"), res["slug"]
    meta = pages.read_meta(res["path"])
    assert meta["target"]["type"] == "file" and meta["target"]["entry"] == "index.html"
    assert meta["sourceMtime"] == int(os.path.getmtime(p) * 1000)
    again = build_screen.build("html", os.path.join(h, "site", ".", "index.html"))
    assert again["slug"] == res["slug"] and again["new"] is False, "every spelling of the path is one page"


@test
def test_html_slug_is_always_a_dns_label():
    for name in ("Über Uns.html", "a_b.c.HTM", "---.html", ("x" * 90) + ".html"):
        s = build_screen.html_slug(os.path.join(new_home(), "Some_Folder", name))
        assert pages.HTML_SLUG_RE.match(s), s
        assert "--" not in s, s


@test
def test_html_cli_needs_the_server():
    h = use_home(new_home())
    p = _copy_single(h)
    code, res = _main_json(["html", p])  # the harness sets REVIEW_DOC_NO_SERVER
    assert code == 5, (code, res)
    assert res["ok"] is False and res["reason"] == "needs-server"
    assert res["message"].startswith("HTML review needs the local review server: "), res
    code, res = _main_json(["html", p, "--no-server"])
    assert code == 5 and res["reason"] == "needs-server"
    pd = os.path.join(h, "pages")
    assert not os.path.isdir(pd) or os.listdir(pd) == [], "nothing is written without a server"


@test
def test_html_cli_hands_over_the_server_link():
    h = use_home(new_home())
    p = _copy_single(h)
    with patch(build_screen.launch, "ensure_server", lambda *a, **k: (4321, None)):
        code, res = _main_json(["html", p])
    assert code == 0, res
    assert res["url"] == "http://127.0.0.1:4321/review/%s.html" % res["slug"] and res["server"] is True


@test
def test_html_refusals():
    h = use_home(new_home())
    p = _copy_single(h)
    local = "HTML review opens local files and localhost only."
    later = "Reviewing a dev server arrives in 1.3. Build or save the page and review the file."
    for argv, msg in ((["html", "https://example.com/"], local),
                      (["html", "http://192.168.1.5:8080/"], local),
                      (["html", "http://localhost.evil.com/"], local),
                      (["html", "file://fileserver/share/index.html"], local),
                      (["html", "http://[::1"], local),
                      (["html", "http://localhost:5173/"], later),
                      (["html", "http://[::1]:5173/x"], later)):
        code, res = _main_json(argv)
        assert code == 4 and res.get("message") == msg, (argv, code, res)
    md = os.path.join(h, "notes.md")
    with open(md, "w", encoding="utf-8", newline="") as fh:
        fh.write("# x\n")
    code, res = _main_json(["html", md])
    assert code == 4 and res["message"] == build_screen.SUPPORTED, res
    code, res = _main_json(["html", p, "--slug", "Bad_Slug"])
    assert code == 2 and "invalid slug" in res["error"], res
    code, res = _main_json(["html", p, "--out", os.path.join(h, "out")])
    assert code == 2 and "--out" in res["error"], res
    code, res = _main_json(["html", os.path.join(h, "missing.html")])
    assert code == 1, res


@test
def test_home_folder_refused_however_spelled():
    h = use_home(new_home())
    f = os.path.join(h, "home")
    os.makedirs(f)
    p = os.path.join(f, "index.html")
    shutil.copy(_fixture_path("site_single.html"), p)
    homes = [f, f + os.sep]
    if os.name == "nt":
        homes.append(f.upper())
    link = os.path.join(h, "home-link")
    try:
        os.symlink(f, link, target_is_directory=True)
        homes.append(link)
    except (OSError, NotImplementedError):
        pass
    for home in homes:
        for target in (p, pathlib.Path(p).as_uri()):
            with patch(build_screen, "_home", lambda home=home: home):
                code, res = _main_json(["html", target])
            assert code == 4 and res.get("message") == build_screen.TOO_WIDE, (home, target, code, res)


@test
def test_a_page_below_home_is_fine():
    h = use_home(new_home())
    p = _copy_single(h)  # <h>/site/index.html, one level below the patched home
    with patch(build_screen, "_home", lambda: h), \
            patch(build_screen.launch, "ensure_server", lambda *a, **k: (4321, None)):
        code, res = _main_json(["html", p])
    assert code == 0, res


@test
def test_filesystem_root_is_refused():
    root = os.path.abspath(os.sep)
    assert build_screen.folder_too_wide(root)
    if os.name == "nt":
        assert build_screen.folder_too_wide(os.path.splitdrive(os.getcwd())[0] + "\\")
    assert not build_screen.folder_too_wide(os.path.join(root, "x"))


@test
def test_a_file_url_is_a_local_path():
    h = use_home(new_home())
    p = _copy_single(h)
    uri = pathlib.Path(p).resolve().as_uri()
    for url in (uri, "file://localhost" + uri[len("file://"):]):
        # Taken as the path it names, so it gets as far as needing the server
        # (the harness sets REVIEW_DOC_NO_SERVER), not a refusal.
        code, res = _main_json(["html", url])
        assert code == 5 and res["reason"] == "needs-server", (url, code, res)
    missing = pathlib.Path(os.path.join(h, "site", "gone.html")).resolve().as_uri()
    code, res = _main_json(["html", missing])
    assert code == 1 and res["error"].startswith("no such file: "), res
    with patch(build_screen.launch, "ensure_server", lambda *a, **k: (4321, None)):
        code, res = _main_json(["html", uri])
    assert code == 0, res
    meta = pages.read_meta(res["path"])
    assert meta["target"]["entry"] == "index.html" and meta["source"] == os.path.abspath(p).replace("\\", "/")


@test
def test_a_linked_entry_is_served_from_where_it_really_is():
    h = use_home(new_home())
    real_dir = os.path.join(h, "real")
    os.makedirs(real_dir)
    real = os.path.join(real_dir, "page.html")
    shutil.copy(_fixture_path("site_single.html"), real)
    link_dir = os.path.join(h, "elsewhere")
    os.makedirs(link_dir)
    link = os.path.join(link_dir, "index.html")
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError) as exc:
        # Windows without the symlink privilege: a junction to the folder is a link too.
        try:
            import _winapi
            link = os.path.join(h, "junction", "page.html")
            _winapi.CreateJunction(real_dir, os.path.dirname(link))
        except (ImportError, OSError, AttributeError):
            print("  (skip) cannot create a link here: %s" % exc)
            return
    res = build_screen.build("html", link)
    meta = pages.read_meta(res["path"])
    want = os.path.realpath(real).replace("\\", "/")
    assert meta["target"] == {"type": "file", "root": os.path.dirname(want), "entry": "page.html"}, meta
    assert meta["source"] == os.path.abspath(link).replace("\\", "/"), "the path the user gave"


@test
def test_html_switch_off_refuses_with_exit_3():
    h = use_home(new_home())
    settings.set_value("html", "off", h)
    code, res = _main_json(["html", _copy_single(h)])
    assert code == 3 and res == {"ok": False, "reason": "disabled", "setting": "html"}, res
