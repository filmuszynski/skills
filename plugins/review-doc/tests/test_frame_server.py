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

import shell

FIX = os.path.join(HERE, "fixtures")
SLUG = "multi-1a2b3c"


def html_page(home, slug, root, entry="index.html", kind="html"):
    """A page in pages/ as build_screen writes one, reduced to what the frame reads."""
    meta = {"slug": slug, "kind": kind, "target": {"type": "file", "root": root, "entry": entry}}
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
    with serving(h) as srv:
        srv.last_request = 0
        frame_request(srv, "GET", "/", host="evil.example:1")
        assert srv.last_request > 0


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

    def broken(slug, target, path):
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

    def early(slug, target, path):
        raise RuntimeError("early")

    h._file_mode = early
    h._serve()
    assert sent == [500], sent
