# -*- coding: utf-8 -*-
"""The frame listener inside the review server (1.2)."""
import io
import json
import os
import re
import shutil
import socket
import time

from harness import test, new_home, HERE
from serverkit import serving, request, frame_request

import pages
import shell

FIX = os.path.join(HERE, "fixtures")
SLUG = "multi-1a2b3c"


def html_page(home, slug, root, entry="index.html", kind="html", source_mtime=None):
    """A page in pages/ as build_screen writes one, reduced to what the frame reads."""
    meta = {"slug": slug, "kind": kind, "target": {"type": "file", "root": root, "entry": entry}}
    if source_mtime is not None:
        meta["sourceMtime"] = source_mtime
    text = "<script>\nwindow.PRESENTER_DATA = %s;\n</script>\n" % shell._json_literal({"meta": meta})
    shell.write(os.path.join(home, "pages", slug + ".html"), text)
    return slug


def plain_site(home):
    """A one-file site, for the tests that only need the routing (Task 3 adds the fixtures)."""
    root = os.path.join(home, "site")
    os.makedirs(root)
    with open(os.path.join(root, "index.html"), "w", encoding="utf-8", newline="") as fh:
        fh.write("<!DOCTYPE html><html><head><title>t</title></head><body>x</body></html>")
    return root


@test
def test_frame_port_is_main_port_plus_100_and_reported():
    h = new_home()
    with serving(h) as srv:
        assert srv.frame_port == srv.port + 100
        status, _, data = request(srv, "GET", "/api/health")
        assert status == 200 and json.loads(data.decode("utf-8"))["framePort"] == srv.frame_port
        info = json.load(io.open(srv.info_path, encoding="utf-8"))
        assert info["framePort"] == srv.frame_port


@test
def test_taken_frame_port_moves_both_listeners_on():
    while True:
        a = socket.socket()
        a.bind(("127.0.0.1", 0))
        p = a.getsockname()[1]
        a.close()
        if p <= 65000:
            break
    blocker = socket.socket()
    try:
        blocker.bind(("127.0.0.1", p + 100))
        blocker.listen(1)
    except OSError:
        pass  # taken already, which is what the test needs
    try:
        h = new_home()
        with serving(h, ports=[p, 0]) as srv:
            assert srv.port != p and srv.frame_port == srv.port + 100
        # The main socket on p was given back when its frame port failed.
        s = socket.socket()
        s.bind(("127.0.0.1", p))
        s.close()
    finally:
        blocker.close()


@test
def test_frame_refuses_wrong_hosts_and_unknown_slugs():
    h = new_home()
    root = plain_site(h)
    html_page(h, SLUG, root)
    html_page(h, "notes-1a2b3c", root, kind="doc")
    with serving(h) as srv:
        fp = srv.frame_port
        assert frame_request(srv, "GET", "/", SLUG)[0] != 403
        assert frame_request(srv, "GET", "/", host="MULTI-1A2B3C.localhost:%d" % fp)[0] != 403, \
            "host names are case-insensitive"
        for host in ("evil.example:%d" % fp, "localhost:%d" % fp, "127.0.0.1:%d" % fp,
                     "%s.localhost:%d" % (SLUG, srv.port), "%s.localhost" % SLUG,
                     "%s.localhost.:%d" % (SLUG, fp), "x.%s.localhost:%d" % (SLUG, fp),
                     "multi_1a2b3c.localhost:%d" % fp, ""):
            assert frame_request(srv, "GET", "/", host=host)[0] == 403, host
        assert frame_request(srv, "GET", "/", "nosuch-1a2b3c")[0] == 403
        assert frame_request(srv, "GET", "/", "notes-1a2b3c")[0] == 403, "an md page has no frame"
        # The main port never answers to a frame name.
        assert request(srv, "GET", "/api/health", host="%s.localhost:%d" % (SLUG, srv.port))[0] == 403


@test
def test_frame_is_read_only():
    h = new_home()
    html_page(h, SLUG, plain_site(h))
    with serving(h) as srv:
        for m in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
            status, hd, _ = frame_request(srv, m, "/", SLUG)
            assert status == 405 and hd.get("allow") == "GET, HEAD", (m, status)


@test
def test_frame_listens_on_ipv6_loopback_when_there_is_one():
    try:
        s = socket.socket(socket.AF_INET6)
        s.bind(("::1", 0))
        s.close()
    except OSError as exc:
        print("  (skip) no IPv6 loopback here: %s" % exc)
        return
    h = new_home()
    html_page(h, SLUG, plain_site(h))
    with serving(h) as srv:
        assert len(srv.frames) == 2
        assert frame_request(srv, "GET", "/", SLUG, address="::1")[0] != 403


@test
def test_frame_requests_count_as_activity():
    h = new_home()
    html_page(h, SLUG, plain_site(h))
    with serving(h) as srv:
        srv.last_request = 0
        assert frame_request(srv, "GET", "/", host="evil.example:1")[0] == 403
        assert frame_request(srv, "GET", "/", "nosuch-1a2b3c")[0] == 403
        assert srv.last_request == 0, "a refused request from any web page keeps nothing alive"
        assert frame_request(srv, "GET", "/", SLUG)[0] == 200
        assert srv.last_request > 0


@test
def test_frame_moves_on_when_ipv6_frame_port_is_taken():
    try:
        probe = socket.socket(socket.AF_INET6)
        probe.bind(("::1", 0))
        probe.close()
    except OSError as exc:
        print("  (skip) no IPv6 loopback here: %s" % exc)
        return
    while True:
        a = socket.socket()
        a.bind(("127.0.0.1", 0))
        p = a.getsockname()[1]
        a.close()
        if p <= 65000:
            break
    blocker = socket.socket(socket.AF_INET6)
    try:
        blocker.bind(("::1", p + 100))
        blocker.listen(1)
    except OSError:
        pass  # taken already, which is what the test needs
    try:
        h = new_home()
        with serving(h, ports=[p, 0]) as srv:
            assert srv.port != p and srv.frame_port == srv.port + 100, (p, srv.port, srv.frame_port)
        # Both IPv4 sockets on p and p + 100 were given back.
        for port in (p, p + 100):
            s = socket.socket()
            s.bind(("127.0.0.1", port))
            s.close()
    finally:
        blocker.close()


@test
def test_stop_closes_the_frame_listeners():
    h = new_home()
    with serving(h) as srv:
        fp = srv.frame_port
    time.sleep(0.3)
    s = socket.socket()
    try:
        assert s.connect_ex(("127.0.0.1", fp)) != 0, "nothing listens on the frame port any more"
    finally:
        s.close()


def site(home, name="site_multi"):
    root = os.path.join(home, "site")
    shutil.copytree(os.path.join(FIX, name), root)
    return root


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))


PROBE_RE = r'<script src="/__review-doc/probe.js" nonce="([0-9a-f]{32})"></script>'


@test
def test_frame_serves_the_site_with_the_probe():
    h = new_home()
    root = site(h)
    html_page(h, SLUG, root)
    with serving(h) as srv:
        status, hd, data = frame_request(srv, "GET", "/", SLUG)
        assert status == 200 and hd["content-type"] == "text/html; charset=utf-8", (status, hd)
        text = data.decode("utf-8")
        m = re.search("<head>" + PROBE_RE, text)
        assert m, text[:200]
        assert hd["cache-control"] == "no-store" and "x-frame-options" not in hd
        again = frame_request(srv, "GET", "/index.html", SLUG)[2].decode("utf-8")
        assert re.search(PROBE_RE, again) and m.group(1) not in again, "a fresh nonce per response"
        for rel, ctype in (("/css/site.css", "text/css"), ("/img/dot.svg", "image/svg+xml"),
                           ("/js/app.js", "text/javascript")):
            status, hd, data = frame_request(srv, "GET", rel, SLUG)
            with open(os.path.join(root, *rel.strip("/").split("/")), "rb") as fh:
                assert status == 200 and data == fh.read(), rel
            assert hd["content-type"] == ctype, (rel, hd["content-type"])
        status, hd, data = frame_request(srv, "GET", "/__review-doc/probe.js", SLUG)
        assert status == 200 and hd["content-type"] == "text/javascript; charset=utf-8"
        assert b"review-doc probe" in data


@test
def test_frame_refuses_what_is_not_the_site():
    h = new_home()
    root = site(h)
    html_page(h, SLUG, root)
    _write(os.path.join(root, ".env"), "SECRET=1")
    _write(os.path.join(root, ".git", "config"), "[core]")
    _write(os.path.join(root, "notes.txt"), "n")
    _write(os.path.join(h, "outside.html"), "outside")
    _write(os.path.join(root, "__review-doc", "probe.js"), "evil")
    with serving(h) as srv:
        for p in ("/.env", "/.git/config", "/notes.txt", "/../outside.html", "/%2e%2e/outside.html",
                  "/__review-doc/other.js", "/missing.html"):
            assert frame_request(srv, "GET", p, SLUG)[0] == 404, p
        assert b"evil" not in frame_request(srv, "GET", "/__review-doc/probe.js", SLUG)[2]


@test
def test_strict_csp_page_gets_our_nonce_beside_its_own():
    h = new_home()
    root = os.path.join(h, "site")
    os.makedirs(root)
    shutil.copy(os.path.join(FIX, "site_csp.html"), os.path.join(root, "index.html"))
    html_page(h, SLUG, root)
    with serving(h) as srv:
        text = frame_request(srv, "GET", "/", SLUG)[2].decode("utf-8")
    nonce = re.search(PROBE_RE, text).group(1)
    assert ("content=\"script-src 'nonce-pagefixture' 'strict-dynamic' 'nonce-%s'; object-src 'none'\""
            % nonce) in text, text
    assert '<script nonce="pagefixture">' in text


@test
def test_entry_with_a_space_and_head_requests():
    h = new_home()
    root = os.path.join(h, "site")
    os.makedirs(root)
    shutil.copy(os.path.join(FIX, "site_single.html"), os.path.join(root, "my page.html"))
    html_page(h, SLUG, root, entry="my page.html")
    with serving(h) as srv:
        status, _, data = frame_request(srv, "GET", "/", SLUG)
        assert status == 200 and b"/__review-doc/probe.js" in data
        assert frame_request(srv, "GET", "/my%20page.html", SLUG)[0] == 200
        status, hd, data = frame_request(srv, "HEAD", "/", SLUG)
        assert status == 200 and data == b"" and int(hd["content-length"]) > 0


@test
def test_a_folder_without_its_slash_is_redirected():
    h = new_home()
    root = site(h)
    html_page(h, SLUG, root)
    _write(os.path.join(root, "sub", "index.html"), "<p>sub</p>")
    _write(os.path.join(root, ".git", "index.html"), "<p>git</p>")
    _write(os.path.join(root, "empty", "x.css"), "b{}")
    with serving(h) as srv:
        status, hd, _ = frame_request(srv, "GET", "/sub", SLUG)
        assert status == 301 and hd["location"] == "/sub/", (status, hd)
        status, hd, _ = frame_request(srv, "GET", "/sub?x=1", SLUG)
        assert status == 301 and hd["location"] == "/sub/?x=1", (status, hd)
        status, _, data = frame_request(srv, "GET", "/sub/", SLUG)
        assert status == 200 and b"<p>sub</p>" in data
        # A redirect never confirms what the frame would refuse.
        for p in ("/.git", "/empty", "/missing", "/css/site.css/"):
            assert frame_request(srv, "GET", p, SLUG)[0] == 404, p


@test
def test_frame_responses_carry_corp_and_html_gets_frame_ancestors():
    h = new_home()
    root = site(h)
    html_page(h, SLUG, root)
    with serving(h) as srv:
        want = "frame-ancestors http://127.0.0.1:%d http://localhost:%d" % (srv.port, srv.port)
        for p in ("/", "/index.html", "/css/site.css", "/__review-doc/probe.js", "/missing.html"):
            status, hd, _ = frame_request(srv, "GET", p, SLUG)
            assert hd.get("cross-origin-resource-policy") == "same-origin", (p, status, hd)
            if p in ("/", "/index.html"):
                assert hd.get("content-security-policy") == want, (p, hd)
            else:
                assert "content-security-policy" not in hd, (p, hd)
        hd = frame_request(srv, "GET", "/", host="evil.example:1")[1]
        assert hd.get("cross-origin-resource-policy") == "same-origin"


@test
def test_byte_range_on_media():
    h = new_home()
    root = site(h)
    html_page(h, SLUG, root)
    payload = bytes(range(256)) * 4
    _write(os.path.join(root, "media", "clip.mp4"), payload)
    with serving(h) as srv:
        status, hd, data = frame_request(srv, "GET", "/media/clip.mp4", SLUG, headers={"Range": "bytes=10-19"})
        assert status == 206 and data == payload[10:20] and hd["content-range"] == "bytes 10-19/1024"
        status, hd, _ = frame_request(srv, "GET", "/media/clip.mp4", SLUG, headers={"Range": "bytes=5000-"})
        assert status == 416 and hd["content-range"] == "bytes */1024"
        status, hd, data = frame_request(srv, "GET", "/media/clip.mp4", SLUG)
        assert status == 200 and hd["accept-ranges"] == "bytes" and data == payload
        assert hd["content-type"] == "video/mp4"


def _source_mtime(srv, slug=SLUG):
    status, _, data = request(srv, "GET", "/api/review-source?slug=" + slug)
    assert status == 200, status
    return json.loads(data.decode("utf-8"))["mtime"]


def _ms(path):
    return int(os.path.getmtime(path) * 1000)


@test
def test_an_asset_newer_than_the_page_is_not_a_change():
    h = new_home()
    root = site(h)
    html_page(h, SLUG, root)
    entry, css = os.path.join(root, "index.html"), os.path.join(root, "css", "site.css")
    old = time.time() - 100
    os.utime(entry, (old, old))
    # copytree keeps the fixture's own mtime, so make "newer than the page" a fact.
    os.utime(css, (old + 50, old + 50))
    with serving(h) as srv:
        frame_request(srv, "GET", "/", SLUG)
        frame_request(srv, "GET", "/css/site.css", SLUG)
        assert _ms(css) > _ms(entry)
        assert _source_mtime(srv) == _ms(entry)


@test
def test_review_source_follows_served_files_and_resets_on_rebuild():
    h = new_home()
    root = site(h)
    html_page(h, SLUG, root)
    entry, css = os.path.join(root, "index.html"), os.path.join(root, "css", "site.css")
    page = os.path.join(h, "pages", SLUG + ".html")
    old = time.time() - 100
    for p in (entry, css, page):
        os.utime(p, (old, old))
    with serving(h) as srv:
        assert _source_mtime(srv) == _ms(entry)
        frame_request(srv, "GET", "/", SLUG)
        frame_request(srv, "GET", "/css/site.css", SLUG)
        assert _source_mtime(srv) == _ms(entry), "served, not changed"
        new = time.time()
        os.utime(css, (new, new))
        assert _source_mtime(srv) == _ms(css), "a changed stylesheet is a changed source"
        # Claude re-renders: the page is rebuilt and the frame reloads its files.
        os.utime(page, (new + 5, new + 5))
        frame_request(srv, "GET", "/", SLUG)
        frame_request(srv, "GET", "/css/site.css", SLUG)
        assert _source_mtime(srv) == _ms(entry), "the record starts again after a rebuild"


def _stale_setup(h):
    """A site, its page built now (sourceMtime = the entry's mtime), everything in the past."""
    root = site(h)
    entry, css = os.path.join(root, "index.html"), os.path.join(root, "css", "site.css")
    old = time.time() - 100
    for p in (entry, css):
        os.utime(p, (old, old))
    html_page(h, SLUG, root, source_mtime=_ms(entry))
    page = os.path.join(h, "pages", SLUG + ".html")
    os.utime(page, (old + 1, old + 1))
    return entry, css, page


def _review_source(srv):
    status, _, data = request(srv, "GET", "/api/review-source?slug=" + SLUG)
    assert status == 200, status
    return json.loads(data.decode("utf-8"))


def _rebuild(h, page, entry, when):
    """What a re-render does: the page is written again, with the entry's mtime now."""
    root = os.path.dirname(entry)
    html_page(h, SLUG, root, source_mtime=_ms(entry))
    os.utime(page, (when, when))


@test
def test_review_source_right_after_a_rebuild_shows_no_change():
    h = new_home()
    entry, css, page = _stale_setup(h)
    with serving(h) as srv:
        frame_request(srv, "GET", "/", SLUG)
        frame_request(srv, "GET", "/css/site.css", SLUG)
        new = time.time()
        os.utime(css, (new, new))
        assert _review_source(srv)["mtime"] == _ms(css)
        # Claude re-renders; the shell asks before the frame has reloaded anything.
        _rebuild(h, page, entry, new + 5)
        got = _review_source(srv)
        assert got["mtime"] == _ms(entry), "no strip after a re-render, even before the frame reloads"
        assert got["page"] == _ms(page), "page tells a waiting page that it was re-rendered"


@test
def test_a_css_edit_served_again_is_no_longer_a_change():
    h = new_home()
    entry, css, _ = _stale_setup(h)
    with serving(h) as srv:
        frame_request(srv, "GET", "/", SLUG)
        frame_request(srv, "GET", "/css/site.css", SLUG)
        assert _review_source(srv)["mtime"] == _ms(entry)
        new = time.time()
        os.utime(css, (new, new))
        assert _review_source(srv)["mtime"] == _ms(css), "an edited stylesheet shows the strip"
        frame_request(srv, "GET", "/css/site.css", SLUG)  # Reload, no re-render
        assert _review_source(srv)["mtime"] == _ms(entry), "the frame has the edit now"


@test
def test_an_entry_edit_served_again_is_no_longer_a_change():
    h = new_home()
    entry, _, _ = _stale_setup(h)
    with serving(h) as srv:
        frame_request(srv, "GET", "/", SLUG)
        built = _ms(entry)
        new = time.time()
        os.utime(entry, (new, new))
        assert _review_source(srv)["mtime"] == _ms(entry) > built
        frame_request(srv, "GET", "/", SLUG)
        assert _review_source(srv)["mtime"] == built


@test
def test_an_entry_edit_before_the_frame_loaded_is_a_change():
    h = new_home()
    entry, _, _ = _stale_setup(h)
    built = _ms(entry)
    new = time.time()
    os.utime(entry, (new, new))
    with serving(h) as srv:
        assert _review_source(srv)["mtime"] == _ms(entry) > built


@test
def test_review_source_for_md_pages_is_unchanged():
    h = new_home()
    md = os.path.join(h, "notes.md")
    _write(md, "# T\n")
    meta = {"slug": "notes-1a2b3c", "kind": "doc", "source": md.replace("\\", "/")}
    shell.write(os.path.join(h, "pages", "notes-1a2b3c.html"),
                "<script>\nwindow.PRESENTER_DATA = %s;\n</script>\n" % shell._json_literal({"meta": meta}))
    with serving(h) as srv:
        assert _source_mtime(srv, "notes-1a2b3c") == _ms(md)


@test
def test_no_second_response_after_headers_went_out():
    import frame_server

    class App(object):
        frame_port = 27877
        last_request = 0

        def __init__(self):
            self.logged = []

        def frame_target(self, slug):
            return {"root": "/", "entry": "index.html"}

        def log(self, msg):
            self.logged.append(msg)

    h = object.__new__(frame_server.FrameHandler)
    h.server = type("S", (), {"app": App()})()
    h.headers = {"Host": "%s.localhost:27877" % SLUG}
    h.path, h.command, h.close_connection = "/x", "GET", False
    sent = []
    h.send_response = lambda code: sent.append(code)
    h.send_header = lambda k, v: None
    h.end_headers = lambda: None
    h.wfile = io.BytesIO()

    def broken(slug, target, path, query=""):
        h._head(200, "text/css", 10)  # the headers are out, then the file fails
        raise RuntimeError("disk went away")

    h._file_mode = broken
    h._serve()
    assert sent == [200], sent  # no 500 on top of the 200
    assert h.close_connection is True and h.wfile.getvalue() == b""
    assert any("disk went away" in m for m in h.server.app.logged)
    # A failure before any header still gets its 500.
    sent[:] = []
    h.close_connection = False

    def early(slug, target, path, query=""):
        raise RuntimeError("early")

    h._file_mode = early
    h._serve()
    assert sent == [500], sent


@test
def test_selfcontained_fixture_served_with_probe():
    h = new_home()
    root = os.path.join(h, "site")
    os.makedirs(root)
    src = os.path.join(FIX, "site_selfcontained.html")
    shutil.copy(src, os.path.join(root, "index.html"))
    html_page(h, SLUG, root)
    with open(src, encoding="utf-8") as fh:
        original = fh.read()
    assert len(original) > 20000, len(original)
    assert "http://" not in original and "https://" not in original
    with serving(h) as srv:
        status, _, data = frame_request(srv, "GET", "/", SLUG)
    text = data.decode("utf-8")
    assert status == 200
    assert len(re.findall(PROBE_RE, text)) == 1
    script = re.search(r"<script>(.*?)</script>", original, re.S).group(0)
    assert script in text


@test
def test_html_page_rebuilt_on_get_when_a_served_file_changed():
    h = new_home()
    entry, css, page = _stale_setup(h)
    with serving(h) as srv:
        frame_request(srv, "GET", "/", SLUG)
        frame_request(srv, "GET", "/css/site.css", SLUG)
        before = os.path.getmtime(page)
        new = time.time() + 10
        os.utime(css, (new, new))
        assert _review_source(srv)["mtime"] == _ms(css)
        status, _, _ = request(srv, "GET", "/review/%s.html" % SLUG)
        assert status == 200
        assert os.path.getmtime(page) > before, "the page was rebuilt"
        meta = pages.read_meta(page)
        assert meta["slug"] == SLUG and meta["kind"] == "html"
        assert _review_source(srv)["mtime"] == meta["sourceMtime"]


@test
def test_html_page_not_rebuilt_without_a_change():
    h = new_home()
    entry, css, page = _stale_setup(h)
    with serving(h) as srv:
        frame_request(srv, "GET", "/", SLUG)
        frame_request(srv, "GET", "/css/site.css", SLUG)
        before = os.path.getmtime(page)
        for _ in range(2):
            status, _, _ = request(srv, "GET", "/review/%s.html" % SLUG)
            assert status == 200
        assert os.path.getmtime(page) == before
