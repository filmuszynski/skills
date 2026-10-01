# -*- coding: utf-8 -*-
import io
import json
import os
import threading
import time

from harness import test, new_home, use_home
from serverkit import serving, request

import build_screen
import layout_doc
import settings
import shell


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def rendered(h, name="notes.md", text="First text."):
    s = write(os.path.join(h, "src", name), "# T\n\n## A\n\n%s\n" % text)
    return s, build_screen.build("doc", s)


def touch_later(path, seconds=5):
    t = time.time() + seconds
    os.utime(path, (t, t))


def spy(srv):
    calls = []
    real = srv.rebuild

    def counting(kind, src, slug):
        calls.append(slug)
        return real(kind, src, slug)
    srv.rebuild = counting
    return calls


@test
def test_serves_a_page():
    h = use_home(new_home())
    _, res = rendered(h)
    with serving(h) as srv:
        status, ctype, data = request(srv, "GET", "/review/%s.html" % res["slug"])
        assert status == 200 and ctype.startswith("text/html")
        assert "First text." in data.decode("utf-8")


@test
def test_missing_page_explains_expiry():
    h = use_home(new_home())
    settings.set_value("stale-hours", "48", h)
    with serving(h) as srv:
        status, ctype, data = request(srv, "GET", "/review/gone-abc123.html")
        text = data.decode("utf-8")
        assert status == 404 and ctype.startswith("text/plain")
        assert "48 hours" in text and "render it again" in text


@test
def test_slugs_cannot_leave_pages():
    h = use_home(new_home())
    write(os.path.join(h, "secret.html"), "SECRET")
    with serving(h) as srv:
        for p in ("/review/../secret.html", "/review/..%2Fsecret.html", "/review/....html",
                  "/review/a%00b.html", "/review/.html", "/review/sub/x.html"):
            status, _, data = request(srv, "GET", p)
            assert status == 404 and b"SECRET" not in data, p


@test
def test_newer_source_is_rebuilt_before_serving():
    h = use_home(new_home())
    s, res = rendered(h)
    write(s, "# T\n\n## A\n\nSecond text.\n")
    touch_later(s)
    with serving(h) as srv:
        calls = spy(srv)
        data = request(srv, "GET", "/review/%s.html" % res["slug"])[2].decode("utf-8")
        assert "Second text." in data and "First text." not in data
        assert calls == [res["slug"]]


@test
def test_fresh_page_is_not_rebuilt():
    h = use_home(new_home())
    _, res = rendered(h)
    with serving(h) as srv:
        calls = spy(srv)
        assert request(srv, "GET", "/review/%s.html" % res["slug"])[0] == 200
        assert calls == []


@test
def test_only_markdown_sources_are_rebuilt():
    h = use_home(new_home())
    txt = write(os.path.join(h, "src", "notes.txt"), "plain")
    for slug, source in (("notes-txt-000000", txt.replace("\\", "/")),
                         ("relative-000000", "src/notes.md")):
        built = layout_doc.build("# T\n\n## A\n\nOld.\n", source=source, slug=slug)
        built["meta"]["sourceMtime"] = 0
        shell.write(os.path.join(h, "pages", slug + ".html"), shell.render(**built))
    write(os.path.join(h, "src", "notes.md"), "# T\n")
    with serving(h) as srv:
        calls = spy(srv)
        for slug in ("notes-txt-000000", "relative-000000"):
            status, _, data = request(srv, "GET", "/review/%s.html" % slug)
            assert status == 200 and "Old." in data.decode("utf-8")
        assert calls == []


@test
def test_failed_rebuild_serves_old_page_and_logs():
    h = use_home(new_home())
    s, res = rendered(h)
    settings.set_value("md", "off", h)  # the rebuild now exits 3
    write(s, "# T\n\n## A\n\nSecond text.\n")
    touch_later(s)
    with serving(h) as srv:
        status, _, data = request(srv, "GET", "/review/%s.html" % res["slug"])
        assert status == 200 and "First text." in data.decode("utf-8")
    log = io.open(os.path.join(h, "server.log"), encoding="utf-8").read()
    assert "rebuild of %s failed (exit 3)" % res["slug"] in log, log


@test
def test_concurrent_requests_rebuild_once():
    h = use_home(new_home())
    s, res = rendered(h)
    write(s, "# T\n\n## A\n\nSecond text.\n")
    touch_later(s)
    with serving(h) as srv:
        calls = spy(srv)
        got = []
        ts = [threading.Thread(target=lambda: got.append(request(srv, "GET", "/review/%s.html" % res["slug"])))
              for _ in range(3)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(30)
        assert [g[0] for g in got] == [200, 200, 200]
        assert all("Second text." in g[2].decode("utf-8") for g in got)
        assert calls == [res["slug"]], calls


@test
def test_review_source_reports_mtime():
    h = use_home(new_home())
    s, res = rendered(h)
    with serving(h) as srv:
        status, _, data = request(srv, "GET", "/api/review-source?slug=" + res["slug"])
        assert status == 200
        assert json.loads(data.decode("utf-8")) == {"mtime": int(os.path.getmtime(s) * 1000)}


@test
def test_deleted_source_serves_page_and_source_is_404():
    h = use_home(new_home())
    s, res = rendered(h)
    os.remove(s)
    with serving(h) as srv:
        calls = spy(srv)
        status, _, data = request(srv, "GET", "/review/%s.html" % res["slug"])
        assert status == 200 and "First text." in data.decode("utf-8")
        assert calls == []
        assert request(srv, "GET", "/api/review-source?slug=" + res["slug"])[0] == 404
        assert request(srv, "GET", "/api/review-source?slug=nope-000000")[0] == 404
        assert request(srv, "GET", "/api/review-source?slug=../config")[0] == 404
