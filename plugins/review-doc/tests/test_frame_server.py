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
