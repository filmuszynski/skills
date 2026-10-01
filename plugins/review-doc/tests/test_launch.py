# -*- coding: utf-8 -*-
import contextlib
import http.server
import io
import json
import os
import signal
import socket
import threading
import time

import harness
from harness import test, new_home, use_home, env, patch
from serverkit import serving

import build_screen
import launch
import paths


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def run_main(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = build_screen.main(argv)
    return code, json.loads(out.getvalue())


def fetch(port, path):
    return launch.OPENER_NO_PROXY.open("http://127.0.0.1:%d%s" % (port, path), timeout=30).read().decode("utf-8")


def stop_server(home):
    """Stop a real server started for home and wait until it is gone. Never this process."""
    info = launch.read_info(home)
    if not info or info.get("pid") == os.getpid():
        return
    if not launch.stop(info["port"], wait=5.0):
        try:
            os.kill(info["pid"], signal.SIGTERM)
        except OSError:
            pass


@test
def test_health_ignores_proxy_settings():
    h = new_home()
    with serving(h) as srv:
        with env(HTTP_PROXY="http://127.0.0.1:9", http_proxy="http://127.0.0.1:9", NO_PROXY=None, no_proxy=None):
            got = launch.health(srv.port)
        assert got is not None and got["pid"] == os.getpid()


@test
def test_health_rejects_closed_port_and_other_apps():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    closed = s.getsockname()[1]
    s.close()
    assert launch.health(closed) is None

    class Other(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            b = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def log_message(self, *a):
            pass
    other = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Other)
    threading.Thread(target=other.serve_forever, daemon=True).start()
    try:
        assert launch.health(other.server_address[1]) is None
    finally:
        other.shutdown()
        other.server_close()


@test
def test_ensure_server_respects_no_server_env():
    h = new_home()

    def boom(home=None):
        raise AssertionError("spawned")
    with patch(launch, "spawn", boom):
        port, why = launch.ensure_server(h)
    assert port is None and "REVIEW_DOC_NO_SERVER" in why


@test
def test_ensure_server_reason_when_nothing_answers():
    h = new_home()
    write(os.path.join(h, "server.log"), "2026-09-30T10:00:00 no free port in 7777-7787; exiting\n")
    with env(REVIEW_DOC_NO_SERVER=None), patch(launch, "spawn", lambda home=None: None):
        t = time.time()
        port, why = launch.ensure_server(h, wait=0.3)
    assert port is None and time.time() - t < 3
    assert "no free port" in why and "server.log" in why, why


@test
def test_main_links_to_server_when_it_answers():
    h = use_home(new_home())
    s = write(os.path.join(h, "src", "a.md"), "# A\n\n## B\n\nx\n")
    with patch(launch, "ensure_server", lambda home=None: (4321, None)):
        code, res = run_main(["doc", s])
    assert code == 0 and res["server"] is True
    assert res["url"] == "http://127.0.0.1:4321/review/%s.html" % res["slug"]
    assert res["new"] is True and res["opened"] is False


@test
def test_main_reports_why_without_server():
    h = use_home(new_home())
    s = write(os.path.join(h, "src", "a.md"), "# A\n\n## B\n\nx\n")
    code, res = run_main(["doc", s])
    assert code == 0 and res["server"] is False and res["url"].startswith("file://")
    assert "REVIEW_DOC_NO_SERVER" in res["serverNote"]
    code, res = run_main(["doc", s])
    assert res["new"] is False, "second render of the same file is not new"


@test
def test_out_folder_and_no_server_flag_skip_the_server():
    h = use_home(new_home())
    s = write(os.path.join(h, "src", "a.md"), "# A\n\n## B\n\nx\n")

    def boom(home=None):
        raise AssertionError("asked for a server")
    with patch(launch, "ensure_server", boom):
        code, res = run_main(["doc", s, "--out", os.path.join(h, "elsewhere")])
        assert code == 0 and res["url"].startswith("file://") and "serverNote" not in res
        code, res = run_main(["doc", s, "--no-server"])
        assert code == 0 and res["server"] is False


@test
def test_one_server_for_concurrent_renders_and_real_rebuild():
    h = use_home(new_home())
    s = write(os.path.join(h, "src", "live.md"), "# Live\n\n## A\n\nFirst text.\n")
    try:
        with env(REVIEW_DOC_NO_SERVER=None):
            got = []
            ts = [threading.Thread(target=lambda: got.append(launch.ensure_server(h))) for _ in range(3)]
            for t in ts:
                t.start()
            for t in ts:
                t.join(20)
            ports = {p for p, _ in got}
            assert len(got) == 3 and len(ports) == 1 and None not in ports, got
            port = ports.pop()
            info = launch.read_info(h)
            assert info["port"] == port and info["pid"] != os.getpid()
            time.sleep(2.5)  # the instances that lost the lock have given up by now
            assert [p for p in harness.PORTS if launch.health(p)] == [port]

            code, res = run_main(["doc", s, "--no-open"])
            assert code == 0 and res["server"] is True
            assert res["url"] == "http://127.0.0.1:%d/review/%s.html" % (port, res["slug"])
            assert "First text." in fetch(port, "/review/%s.html" % res["slug"])

            write(s, "# Live\n\n## A\n\nSecond text.\n")
            later = time.time() + 5
            os.utime(s, (later, later))
            assert "Second text." in fetch(port, "/review/%s.html" % res["slug"])
    finally:
        stop_server(h)


@test
def test_an_older_server_hands_over_to_this_version():
    h = use_home(new_home())
    try:
        with serving(h, version="0.0.1-old", tick=0.05) as old:
            with env(REVIEW_DOC_NO_SERVER=None):
                port, why = launch.ensure_server(h)
            assert port is not None, why
            assert old.stopping.is_set(), "the old server was asked to stop"
            got = launch.health(port)
            assert got["version"] == paths.version() and got["pid"] != os.getpid()
    finally:
        stop_server(h)
