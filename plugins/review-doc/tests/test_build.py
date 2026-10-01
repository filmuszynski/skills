# -*- coding: utf-8 -*-
import io
import json
import os
import time

from harness import test, new_home, use_home, HERE

import build_screen
import pages
import paths
import settings


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def src(home, name="notes.md", body="# T\n\n## A\n\nText.\n"):
    return write(os.path.join(home, "src", name), body)


@test
def test_page_lands_in_home_pages_with_hashed_slug():
    h = use_home(new_home())
    s = src(h)
    res = build_screen.build("doc", s)
    assert res["slug"].startswith("src-notes-") and len(res["slug"].rsplit("-", 1)[1]) == 6, res["slug"]
    assert os.path.isfile(os.path.join(h, "pages", res["slug"] + ".html"))
    assert res["url"].startswith("file://") and res["server"] is False


@test
def test_same_file_two_spellings_one_slug():
    h = use_home(new_home())
    s = src(h)
    rel = os.path.relpath(s)
    assert build_screen.default_slug("doc", s) == build_screen.default_slug("doc", rel)
    if os.name == "nt":
        flipped = s[0].swapcase() + s[1:]
        assert build_screen.default_slug("doc", s) == build_screen.default_slug("doc", flipped)


@test
def test_two_readmes_in_two_projects_differ():
    h = new_home()
    a = src(h, os.path.join("p1", "docs", "README.md"))
    b = src(h, os.path.join("p2", "docs", "README.md"))
    assert build_screen.default_slug("doc", a) != build_screen.default_slug("doc", b)


@test
def test_meta_carries_absolute_source_and_version():
    h = use_home(new_home())
    s = src(h)
    res = build_screen.build("doc", s)
    html = io.open(os.path.join(h, "pages", res["slug"] + ".html"), encoding="utf-8").read()
    want = os.path.abspath(s).replace("\\", "/")
    assert json.dumps(want)[1:-1] in html, want
    assert '"version": "%s"' % paths.version() in html
    assert res["source"] == want


@test
def test_non_ascii_and_spaces_in_path():
    # The space must be in the home folder itself: a checkout path without one (as on
    # CI runners) would otherwise leave nothing for the URL to quote.
    h = os.path.join(new_home(), "home with space")
    os.makedirs(h)
    use_home(h)
    s = src(h, u"Übersicht notes.md")
    res = build_screen.build("doc", s)
    assert all(ord(c) < 128 for c in res["slug"]), res["slug"]
    assert os.path.isfile(os.path.join(h, "pages", res["slug"] + ".html"))
    assert "%20" in res["url"], res["url"]


@test
def test_md_switched_off_refuses_with_exit_3():
    h = use_home(new_home())
    settings.set_value("md", "off", h)
    s = src(h)
    assert build_screen.main(["doc", s]) == 3
    pd = os.path.join(h, "pages")
    assert not os.path.isdir(pd) or not os.listdir(pd), "a disabled kind must write nothing"


@test
def test_choice_switched_off_refuses_screens():
    h = use_home(new_home())
    settings.set_value("choice", "off", h)
    body = io.open(os.path.join(HERE, "fixtures", "screen_options.md"), encoding="utf-8-sig").read()
    s = write(os.path.join(h, "src", "pick.md"), body)
    try:
        build_screen.build("screen", s)
    except build_screen.Disabled as exc:
        assert exc.setting == "choice"
    else:
        raise AssertionError("screen rendered although choice is off")


@test
def test_prune_deletes_only_old_pages():
    h = new_home()
    pd = os.path.join(h, "pages")
    os.makedirs(pd)
    old, fresh = os.path.join(pd, "old.html"), os.path.join(pd, "fresh.html")
    keep = [os.path.join(h, "config.json"), os.path.join(h, "server.json"), os.path.join(pd, "notes.txt")]
    for p in [old, fresh] + keep:
        write(p, "x")
    os.makedirs(os.path.join(pd, "sub"))
    now = time.time()
    os.utime(old, (now - 97 * 3600, now - 97 * 3600))
    for p in keep:
        os.utime(p, (now - 500 * 3600, now - 500 * 3600))
    assert pages.prune(home=h, now=now, hours=96) == 1
    assert not os.path.exists(old) and os.path.exists(fresh)
    assert all(os.path.exists(p) for p in keep) and os.path.isdir(os.path.join(pd, "sub"))


@test
def test_render_prunes_with_the_configured_window():
    h = use_home(new_home())
    settings.set_value("stale-hours", "1", h)
    pd = os.path.join(h, "pages")
    os.makedirs(pd)
    old = write(os.path.join(pd, "old.html"), "x")
    os.utime(old, (time.time() - 2 * 3600,) * 2)
    build_screen.build("doc", src(h))
    assert not os.path.exists(old)


@test
def test_bare_name_and_absolute_path_give_one_slug():
    """Review fix: the name part came from the path as typed, the hash from the normalised one."""
    h = new_home()
    s = src(h)
    here = os.getcwd()
    os.chdir(os.path.dirname(s))
    try:
        bare = build_screen.default_slug("doc", os.path.basename(s))
        dotted = build_screen.default_slug("doc", "." + os.sep + os.path.basename(s))
    finally:
        os.chdir(here)
    assert bare == dotted == build_screen.default_slug("doc", s), (bare, dotted)


@test
def test_explicit_slug_cannot_escape_pages():
    h = use_home(new_home())
    s = src(h)
    escaped = os.path.join(os.path.dirname(h), "escaped.html")
    if os.path.exists(escaped):
        os.remove(escaped)  # left by a run before the fix
    for bad in ("../../escaped", "..\escaped", "a/b", "", "x y"):
        try:
            build_screen.build("doc", s, slug=bad)
        except ValueError:
            pass
        else:
            raise AssertionError("accepted slug %r" % bad)
    assert build_screen.main(["doc", s, "--slug", "../../escaped"]) == 2
    assert not os.path.exists(escaped)


@test
def test_harness_keeps_servers_and_browsers_out():
    import harness
    assert os.environ["REVIEW_DOC_NO_SERVER"] == "1"
    assert os.environ["REVIEW_DOC_NO_OPEN"] == "1"
    assert os.environ["REVIEW_DOC_PORTS"] == "27777-27787"
    assert list(harness.PORTS) == list(range(27777, 27788))
    with harness.env(REVIEW_DOC_NO_OPEN=None, SOME_TEST_VAR="x"):
        assert "REVIEW_DOC_NO_OPEN" not in os.environ and os.environ["SOME_TEST_VAR"] == "x"
    assert os.environ["REVIEW_DOC_NO_OPEN"] == "1" and "SOME_TEST_VAR" not in os.environ
    with harness.patch(pages, "prune", "patched"):
        assert pages.prune == "patched"
    assert callable(pages.prune)


@test
def test_read_meta_round_trip():
    h = use_home(new_home())
    s = src(h)
    res = build_screen.build("doc", s)
    meta = pages.read_meta(os.path.join(h, "pages", res["slug"] + ".html"))
    assert meta["slug"] == res["slug"] and meta["kind"] == "doc"
    assert meta["source"] == res["source"]
    assert isinstance(meta["sourceMtime"], int)


@test
def test_read_meta_none_for_junk():
    h = new_home()
    assert pages.read_meta(os.path.join(h, "missing.html")) is None
    junk = write(os.path.join(h, "junk.html"), "<html>no data here</html>")
    assert pages.read_meta(junk) is None
    broken = write(os.path.join(h, "broken.html"), "<script>\nwindow.PRESENTER_DATA = {nope;\n</script>")
    assert pages.read_meta(broken) is None


def _main_json(argv):
    import contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = build_screen.main(argv)
    return code, json.loads(out.getvalue())


@test
def test_html_files_are_refused_until_v1_1():
    h = use_home(new_home())
    for name in ("page.html", "page.HTM"):
        src = write(os.path.join(h, name), "<h1>x</h1>\n")
        code, res = _main_json(["doc", src])
        assert code == 4, (name, code)
        assert res == {"ok": False, "reason": "unsupported",
                       "message": "HTML review arrives in review-doc 1.2."}, res
    pd = os.path.join(h, "pages")
    assert not os.path.isdir(pd) or os.listdir(pd) == []


@test
def test_other_file_types_are_refused_with_the_supported_ones():
    h = use_home(new_home())
    for name in ("notes.txt", "README", "plan.md.bak"):
        src = write(os.path.join(h, name), "# x\n")
        for kind in ("doc", "plan", "screen"):
            code, res = _main_json([kind, src])
            assert code == 4, (name, kind, code)
            assert res["message"] == "review-doc reviews Markdown files (.md, .markdown).", res


@test
def test_markdown_extensions_in_any_case_render():
    h = use_home(new_home())
    for name in ("a.markdown", "b.MD", "c.Markdown"):
        src = write(os.path.join(h, name), "# T\n\n## A\n\nx\n")
        code, res = _main_json(["doc", src])
        assert code == 0 and res["ok"] is True, (name, res)


@test
def test_cli_output_survives_a_pipe_outside_the_code_page():
    """The skills run the renderer from a shell, where nothing sets PYTHONIOENCODING.
    On Windows a pipe then uses the ANSI code page, which has no letter for a Polish L."""
    import subprocess
    import sys
    h = new_home()
    src = write(os.path.join(h, "notizen-\u0142\u00f3d\u017a.md"), "# Notizen zu \u0141\u00f3d\u017a\n\n## A\n\nx\n")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    env["REVIEW_DOC_HOME"] = h
    r = subprocess.run([sys.executable, build_screen.__file__, "doc", src], env=env,
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-300:]
    res = json.loads(r.stdout.decode("ascii"))
    assert res["title"] == "Notizen zu \u0141\u00f3d\u017a", res["title"]
    import extension
    r = subprocess.run([sys.executable, extension.__file__, "install", "--vsix",
                        os.path.join(h, "\u0141\u00f3d\u017a.vsix")], env=env,
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    assert r.returncode == 1, r.stderr.decode("utf-8", "replace")[-300:]
    assert json.loads(r.stdout.decode("ascii"))["ok"] is False


def fixture_path_for_choice(h):
    p = os.path.join(h, "pick.md")
    with io.open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write("# Pick one\n\n## Option A\n\nFirst.\n\n## Option B\n\nSecond.\n")
    return p


@test
def test_doc_and_plan_pages_carry_the_facts():
    h = use_home(new_home())
    src = os.path.join(h, "note.md")
    with io.open(src, "w", encoding="utf-8", newline="") as fh:
        fh.write("# Note\n\n## One\n\nText.\n")
    res = build_screen.build("doc", src, out_dir=os.path.join(h, "out"))
    html = io.open(res["path"], encoding="utf-8").read()
    assert '<tr class="glance-fact"><th>Draft</th><td>1</td></tr>' in html
    assert "<th>Last edited</th>" in html
    assert os.path.isfile(os.path.join(h, "drafts", res["slug"] + ".json")), "--out still keeps the record at home"
    plan = os.path.join(h, "plan.md")
    with io.open(plan, "w", encoding="utf-8", newline="") as fh:
        fh.write("# Plan\n\n## Task 1: t\n\nx\n")
    html = io.open(build_screen.build("plan", plan, out_dir=os.path.join(h, "out"))["path"], encoding="utf-8").read()
    assert '<tr class="glance-fact"><th>Draft</th><td>1</td></tr>' in html


@test
def test_a_requested_round_shows_as_draft_two_after_the_edit():
    import drafts
    h = use_home(new_home())
    src = os.path.join(h, "note.md")
    with io.open(src, "w", encoding="utf-8", newline="") as fh:
        fh.write("# Note\n\nText.\n")
    res = build_screen.build("doc", src, out_dir=os.path.join(h, "out"))
    drafts.request(res["slug"], int(os.path.getmtime(src) * 1000))
    later = os.path.getmtime(src) + 5
    os.utime(src, (later, later))
    html = io.open(build_screen.build("doc", src, out_dir=os.path.join(h, "out"))["path"], encoding="utf-8").read()
    assert '<th>Draft</th><td>2</td>' in html


@test
def test_choice_screens_get_no_facts():
    h = use_home(new_home())
    src = fixture_path_for_choice(h)
    html = io.open(build_screen.build("screen", src, out_dir=os.path.join(h, "out"))["path"], encoding="utf-8").read()
    # The shell's own JS and CSS name the class, so look for the row markup.
    assert '<tr class="glance-fact"' not in html
    assert not os.path.isdir(os.path.join(h, "drafts"))
