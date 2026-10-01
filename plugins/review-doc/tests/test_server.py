# -*- coding: utf-8 -*-
import datetime
import io
import json
import os
import socket

from harness import test, new_home
from serverkit import serving, request, post_json, review_server

import settings


def body(data):
    return json.loads(data.decode("utf-8"))


@test
def test_health_and_server_json():
    h = new_home()
    with serving(h, version="9.9.9") as srv:
        status, ctype, data = request(srv, "GET", "/api/health")
        assert status == 200 and ctype.startswith("application/json")
        assert body(data) == {"ok": True, "version": "9.9.9", "port": srv.port, "pid": os.getpid()}
        info = json.load(io.open(srv.info_path, encoding="utf-8"))
        assert info["port"] == srv.port and info["pid"] == os.getpid()
        datetime.datetime.fromisoformat(info["started"])
        # 127.0.0.1 is as good as localhost
        assert request(srv, "GET", "/api/health", host="127.0.0.1:%d" % srv.port)[0] == 200
    assert not os.path.exists(srv.info_path), "server.json goes with the server"


@test
def test_wrong_host_is_forbidden():
    h = new_home()
    with serving(h) as srv:
        for host in ("evil.example:%d" % srv.port, "localhost:1", "localhost", "127.0.0.1"):
            status, _, data = request(srv, "GET", "/api/health", host=host)
            assert status == 403, (host, status)
            assert b"version" not in data


@test
def test_missing_host_is_forbidden():
    h = new_home()
    with serving(h) as srv:
        s = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
        s.sendall(b"GET /api/health HTTP/1.0\r\n\r\n")
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()
        assert data.split(b"\r\n", 1)[0].split(b" ")[1] == b"403", data[:60]


@test
def test_taken_port_falls_through_to_the_next():
    h = new_home()
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    taken = blocker.getsockname()[1]
    try:
        with serving(h, ports=[taken, 0]) as srv:
            assert srv.port != taken
            assert request(srv, "GET", "/api/health")[0] == 200
    finally:
        blocker.close()


@test
def test_all_ports_taken_exits_2_without_server_json():
    h = new_home()
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    try:
        srv = review_server.ReviewServer(home=h, ports=[blocker.getsockname()[1]])
        assert srv.start() == 2
        assert not os.path.exists(srv.info_path)
        log = io.open(os.path.join(h, "server.log"), encoding="utf-8").read()
        assert "no free port" in log
        again = review_server.Lock(os.path.join(h, "server.lock"))
        assert again.acquire(0), "the lock is released on the way out"
        again.release()
    finally:
        blocker.close()


@test
def test_second_instance_exits_while_lock_is_held():
    h = new_home()
    held = review_server.Lock(os.path.join(h, "server.lock"))
    assert held.acquire(0)
    try:
        srv = review_server.ReviewServer(home=h, ports=[0], lock_wait=0.2)
        assert srv.start() == 1
        assert srv.httpd is None and not os.path.exists(srv.info_path)
    finally:
        held.release()


@test
def test_get_settings():
    h = new_home()
    settings.set_value("stale-hours", "48", h)
    with serving(h) as srv:
        status, _, data = request(srv, "GET", "/api/settings")
        assert status == 200 and body(data)["stale_hours"] == 48
        settings.set_value("stale-hours", "12", h)  # re-read on every request
        assert body(request(srv, "GET", "/api/settings")[2])["stale_hours"] == 12


@test
def test_post_settings_saves_and_returns_state():
    h = new_home()
    with serving(h) as srv:
        status, _, data = post_json(srv, "/api/settings", {"stale_hours": 24, "kinds": {"choice": False}})
        assert status == 200, data
        got = body(data)
        assert got["stale_hours"] == 24 and got["kinds"]["choice"] is False
        assert settings.load(h) == got
        # charset in the content type is fine
        status, _, _ = post_json(srv, "/api/settings", {"auto_open": False},
                                 headers={"Content-Type": "application/json; charset=utf-8"})
        assert status == 200 and settings.load(h)["auto_open"] is False


@test
def test_post_settings_needs_json_and_same_origin():
    h = new_home()
    with serving(h) as srv:
        ok = {"stale_hours": 5}
        assert post_json(srv, "/api/settings", ok, headers={"Content-Type": "text/plain"})[0] == 415
        assert post_json(srv, "/api/settings", ok, origin=None)[0] == 403
        assert post_json(srv, "/api/settings", ok, origin="http://evil.example")[0] == 403
        assert post_json(srv, "/api/settings", ok, origin="http://localhost:1")[0] == 403
        assert settings.load(h)["stale_hours"] == 96, "nothing saved"


@test
def test_post_settings_bad_value_is_400_with_field():
    h = new_home()
    with serving(h) as srv:
        status, _, data = post_json(srv, "/api/settings", {"stale_hours": 0})
        assert status == 400 and body(data)["field"] == "stale_hours" and body(data)["ok"] is False
        status, _, data = post_json(srv, "/api/settings", {"kinds": {"md": "yes"}})
        assert status == 400 and body(data)["field"] == "kinds.md"
        assert not os.path.exists(os.path.join(h, "config.json"))


@test
def test_post_rejects_bad_json_and_big_bodies():
    h = new_home()
    with serving(h) as srv:
        status, _, data = post_json(srv, "/api/settings", "{nope")
        assert status == 400 and body(data)["field"] is None
        big = json.dumps({"stale_hours": 5, "pad": "x" * (70 * 1024)})
        assert post_json(srv, "/api/settings", big)[0] == 413


@test
def test_stop_needs_same_origin_and_then_stops():
    h = new_home()
    with serving(h) as srv:
        assert post_json(srv, "/api/stop", {}, origin=None)[0] == 403
        assert not srv.stopping.is_set()
        assert post_json(srv, "/api/stop", {})[0] == 200
        srv.thread.join(5)
        assert not srv.thread.is_alive()


@test
def test_unknown_path_and_method():
    h = new_home()
    with serving(h) as srv:
        assert request(srv, "GET", "/nothing")[0] == 404
        assert post_json(srv, "/api/health", {})[0] == 404
        assert request(srv, "PUT", "/api/settings", body="{}")[0] == 501


@test
def test_a_page_on_127_0_0_1_can_save_settings():
    """Links point at 127.0.0.1 (M-6), so that is the Origin a page's Save sends."""
    h = new_home()
    with serving(h) as srv:
        origin = "http://127.0.0.1:%d" % srv.port
        status, _, data = request(srv, "POST", "/api/settings", body=json.dumps({"stale_hours": 12}),
                                  headers={"Content-Type": "application/json", "Origin": origin},
                                  host="127.0.0.1:%d" % srv.port)
        assert status == 200, data
        assert settings.load(h)["stale_hours"] == 12
        # A page on localhost cannot post with a 127.0.0.1 origin, or the other way round.
        status, _, _ = request(srv, "POST", "/api/settings", body="{}",
                               headers={"Content-Type": "application/json", "Origin": origin})
        assert status == 403


@test
def test_early_answers_to_a_post_read_its_body_first():
    """A POST refused before its body was read made Windows reset the connection
    (WinError 10053) when the body arrived after the answer: the client never saw
    the 404, 403 or 415. The body now arrives late on purpose."""
    import time
    h = new_home()
    with serving(h) as srv:
        cases = (("/api/health", "Origin: http://localhost:%d\r\nContent-Type: application/json\r\n" % srv.port, b" 404 "),
                 ("/api/settings", "Origin: http://evil.example\r\nContent-Type: application/json\r\n", b" 403 "),
                 ("/api/settings", "Origin: http://localhost:%d\r\nContent-Type: text/plain\r\n" % srv.port, b" 415 "))
        for path, extra, want in cases:
            s = socket.create_connection(("127.0.0.1", srv.port), timeout=10)
            try:
                s.sendall(("POST %s HTTP/1.1\r\nHost: localhost:%d\r\n%sContent-Length: 20\r\n\r\n"
                           % (path, srv.port, extra)).encode("ascii"))
                time.sleep(0.2)
                s.sendall(b'{"a":"xxxxxxxxxxxx"}')
                time.sleep(0.2)
                got = s.recv(4096)
            finally:
                s.close()
            assert want in got.split(b"\r\n", 1)[0], (path, got[:40])


def make_page(home, slug):
    import paths
    d = paths.pages_dir(home)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, slug + ".html")
    io.open(p, "w", encoding="utf-8", newline="").close()
    return p


@test
def test_draft_request_and_cancel():
    import drafts
    h = new_home()
    make_page(h, "spec-1")
    with serving(h) as srv:
        status, _, data = post_json(srv, "/api/draft", {"slug": "spec-1", "action": "request", "sourceMtime": 1000})
        assert status == 200 and body(data) == {"ok": True, "draft": 1, "pending": True}, (status, data)
        assert drafts.load("spec-1", home=h)["pending"] == {"sourceMtime": 1000}
        status, _, data = post_json(srv, "/api/draft", {"slug": "spec-1", "action": "cancel"})
        assert status == 200 and body(data) == {"ok": True, "draft": 1, "pending": False}, (status, data)
        assert drafts.load("spec-1", home=h)["pending"] is None


@test
def test_draft_refusals():
    h = new_home()
    make_page(h, "spec-1")
    with serving(h) as srv:
        good = {"slug": "spec-1", "action": "request", "sourceMtime": 1000}
        assert post_json(srv, "/api/draft", good, origin="http://evil.example")[0] == 403
        assert post_json(srv, "/api/draft", good, headers={"Content-Type": "text/plain"})[0] == 415
        assert post_json(srv, "/api/draft", dict(good, slug="nope"))[0] == 404
        assert post_json(srv, "/api/draft", dict(good, slug="../x"))[0] == 404
        assert post_json(srv, "/api/draft", dict(good, action="explode"))[0] == 400
        assert post_json(srv, "/api/draft", dict(good, sourceMtime="soon"))[0] == 400
        assert post_json(srv, "/api/draft", dict(good, sourceMtime=True))[0] == 400
        assert post_json(srv, "/api/draft", "not json")[0] == 400
        assert not os.path.isdir(os.path.join(h, "drafts")), "nothing refused writes a record"


@test
def test_draft_unwritable_record_answers_500():
    h = new_home()
    make_page(h, "spec-1")
    io.open(os.path.join(h, "drafts"), "w", encoding="utf-8", newline="").close()
    with serving(h) as srv:
        status, _, data = post_json(srv, "/api/draft", {"slug": "spec-1", "action": "request", "sourceMtime": 1000})
        assert status == 500 and body(data)["ok"] is False, (status, data)
