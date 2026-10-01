# -*- coding: utf-8 -*-
"""The local server for review pages. Standard library only.

    python server/review_server.py

Binds 127.0.0.1 on the first free port of 7777-7787, records {port, pid, started} in
~/.review-doc/server.json, and exits after 12 hours without a request. There is one
server per home folder: a lock file decides, and a second instance gives up.
"""
from __future__ import print_function

import datetime
import http.server
import io
import json
import os
import re
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from urllib.parse import parse_qs, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
PRESENTER = os.path.join(os.path.dirname(HERE), "presenter")
sys.path.insert(0, PRESENTER)

import pages  # noqa: E402
import paths  # noqa: E402
import settings  # noqa: E402

DEFAULT_PORTS = range(7777, 7788)
IDLE_SECONDS = 12 * 3600
PRUNE_SECONDS = 3600
LOCK_WAIT = 2.0
MAX_BODY = 64 * 1024
MAX_LOG = 1000 * 1000
BUILD_SCREEN = os.path.join(PRESENTER, "build_screen.py")
SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# meta.kind -> the build_screen subcommand that renders it
CLI_KIND = {"plan": "plan", "doc": "doc", "options": "screen", "explain": "screen"}

if os.name == "nt":
    import msvcrt

    def _lock(fh):
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(fh):
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock(fh):
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fh):
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _now_iso():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def _read_json(path):
    try:
        with io.open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write_json(path, obj):
    fd, tmp = tempfile.mkstemp(prefix=".server-", suffix=".tmp", dir=os.path.dirname(path))
    os.close(fd)
    try:
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(obj, fh)
        paths.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def ports_from_env():
    m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", os.environ.get("REVIEW_DOC_PORTS", ""))
    if m and 0 < int(m.group(1)) <= int(m.group(2)) < 65536:
        return range(int(m.group(1)), int(m.group(2)) + 1)
    return DEFAULT_PORTS


def source_of(meta):
    """The page's Markdown source, if it is one the server may rebuild from."""
    src = (meta or {}).get("source")
    if not isinstance(src, str) or not os.path.isabs(src):
        return None
    if not src.lower().endswith((".md", ".markdown")):
        return None
    return src if os.path.isfile(src) else None


class Lock(object):
    """An exclusive lock held for the life of the process. The OS drops it if the
    process dies, so a crash never leaves a stale lock behind."""

    def __init__(self, path):
        self.path = path
        self.fh = None

    def acquire(self, wait=LOCK_WAIT):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fh = open(self.path, "a+")
        deadline = time.time() + wait
        while True:
            try:
                _lock(fh)
                self.fh = fh
                return True
            except OSError:
                if time.time() >= deadline:
                    fh.close()
                    return False
                time.sleep(0.1)

    def release(self):
        if self.fh is None:
            return
        try:
            _unlock(self.fh)
        except OSError:
            pass
        self.fh.close()
        self.fh = None


class _HTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second socket bind a port that is already in use,
    # which would defeat the port fallback. POSIX needs it to rebind after a restart.
    allow_reuse_address = os.name != "nt"
    app = None

    def server_bind(self):
        # HTTPServer.server_bind calls getfqdn(), which can stall for seconds on some
        # networks. The name is never used.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "localhost", self.server_address[1]

    def handle_error(self, request, client_address):
        if self.app is not None:
            self.app.log("request error: %s" % traceback.format_exc().strip().splitlines()[-1])


class ReviewServer(object):
    def __init__(self, home=None, ports=None, idle_seconds=IDLE_SECONDS,
                 prune_seconds=PRUNE_SECONDS, tick=60.0, lock_wait=LOCK_WAIT, version=None):
        self.home = os.path.abspath(home or paths.home_dir())
        self.ports = list(ports if ports is not None else DEFAULT_PORTS)
        self.idle_seconds = idle_seconds
        self.prune_seconds = prune_seconds
        self.tick = tick
        self.lock_wait = lock_wait
        self.version = version or paths.version()
        self.port = None
        self.httpd = None
        self.thread = None
        self.last_request = time.time()
        self.stopping = threading.Event()
        self._lock = Lock(os.path.join(self.home, "server.lock"))
        self._guard = threading.Lock()
        self._rebuilding = {}

    @property
    def info_path(self):
        return os.path.join(self.home, "server.json")

    def log(self, msg):
        try:
            with io.open(os.path.join(self.home, "server.log"), "a", encoding="utf-8") as fh:
                fh.write("%s %s\n" % (_now_iso(), msg))
        except OSError:
            pass

    def start(self):
        """Lock, bind, record. 0 means serve() may run; 1 another server holds the
        lock; 2 no free port."""
        os.makedirs(self.home, exist_ok=True)
        try:
            if os.path.getsize(os.path.join(self.home, "server.log")) > MAX_LOG:
                os.remove(os.path.join(self.home, "server.log"))
        except OSError:
            pass
        if not self._lock.acquire(self.lock_wait):
            self.log("another server holds %s; exiting" % self._lock.path)
            return 1
        for port in self.ports:
            try:
                httpd = _HTTPServer(("127.0.0.1", port), Handler)
            except OSError:
                continue
            httpd.app = self
            self.httpd, self.port = httpd, httpd.server_address[1]
            break
        if self.httpd is None:
            span = "%d-%d" % (min(self.ports), max(self.ports)) if self.ports else "(none)"
            self.log("no free port in %s; exiting" % span)
            self._lock.release()
            return 2
        _write_json(self.info_path, {"port": self.port, "pid": os.getpid(), "started": _now_iso()})
        self.log("serving on 127.0.0.1:%d, version %s, pid %d" % (self.port, self.version, os.getpid()))
        self._prune()
        return 0

    def serve(self):
        worker = threading.Thread(target=self._housekeeping, daemon=True)
        worker.start()
        try:
            self.httpd.serve_forever(poll_interval=0.2)
        finally:
            self.close()

    def stop(self):
        if self.stopping.is_set():
            return
        self.stopping.set()
        if self.httpd is not None:
            # shutdown() blocks until serve_forever returns, so never on its own thread.
            threading.Thread(target=self.httpd.shutdown, daemon=True).start()

    def close(self):
        self.stopping.set()
        info = _read_json(self.info_path)
        if isinstance(info, dict) and info.get("pid") == os.getpid() and info.get("port") == self.port:
            try:
                os.remove(self.info_path)
            except OSError:
                pass
        if self.httpd is not None:
            self.httpd.server_close()
        self._lock.release()
        self.log("stopped")

    def _prune(self):
        try:
            gone = pages.prune(self.home)
            if gone:
                self.log("pruned %d page(s)" % gone)
        except Exception as exc:  # noqa: BLE001  pruning must never stop the server
            self.log("prune failed: %s" % exc)

    def _housekeeping(self):
        last_prune = time.time()
        while not self.stopping.wait(self.tick):
            now = time.time()
            if now - self.last_request >= self.idle_seconds:
                self.log("idle for %d seconds; exiting" % int(now - self.last_request))
                self.stop()
                return
            if now - last_prune >= self.prune_seconds:
                last_prune = now
                self._prune()

    def page_path(self, slug):
        """pages/<slug>.html, or None when the slug could name anything else."""
        if not SLUG_RE.match(slug or "") or slug.strip(".") == "":
            return None
        folder = os.path.realpath(paths.pages_dir(self.home))
        path = os.path.join(folder, slug + ".html")
        return path if os.path.dirname(os.path.realpath(path)) == folder else None

    def freshen(self, slug, path):
        """Rebuild the page first if its source is newer than the page says.
        Any failure serves the page as it is: a stale page beats no page."""
        meta = pages.read_meta(path)
        src = source_of(meta)
        kind = CLI_KIND.get((meta or {}).get("kind"))
        if not src or not kind:
            return False
        built = meta.get("sourceMtime")
        if not isinstance(built, int) or isinstance(built, bool):
            built = int(os.path.getmtime(path) * 1000)
        try:
            now = int(os.path.getmtime(src) * 1000)
        except OSError:
            return False
        if now <= built:
            return False
        with self._guard:
            lock = self._rebuilding.setdefault(slug, threading.Lock())
        with lock:
            # Another request may have rebuilt it while this one waited.
            again = (pages.read_meta(path) or {}).get("sourceMtime")
            if isinstance(again, int) and now <= again:
                return True
            return self.rebuild(kind, src, slug)

    def rebuild_python(self):
        # The server runs under pythonw on Windows; a child whose output is read wants
        # the console interpreter, started without a window.
        exe = sys.executable
        if os.path.basename(exe).lower() == "pythonw.exe":
            console = os.path.join(os.path.dirname(exe), "python.exe")
            if os.path.isfile(console):
                return console
        return exe

    def rebuild(self, kind, src, slug):
        cmd = [self.rebuild_python(), BUILD_SCREEN, kind, src, "--slug", slug, "--no-open", "--no-server"]
        env = dict(os.environ, REVIEW_DOC_HOME=self.home, PYTHONIOENCODING="utf-8")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            r = subprocess.run(cmd, cwd=self.home, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=30, creationflags=flags)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.log("rebuild of %s failed: %s" % (slug, exc))
            return False
        if r.returncode != 0:
            detail = (r.stdout or b"").decode("utf-8", "replace").strip()[-300:]
            self.log("rebuild of %s failed (exit %d): %s" % (slug, r.returncode, detail))
            return False
        self.log("rebuilt %s" % slug)
        return True


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "review-doc"

    def log_message(self, fmt, *args):
        pass  # requests are not logged; errors go to server.log through app.log

    @property
    def app(self):
        return self.server.app

    def _send(self, code, payload, ctype):
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _text(self, code, text):
        self._send(code, text, "text/plain; charset=utf-8")

    def _host(self):
        return (self.headers.get("Host") or "").strip().lower()

    def _begin(self):
        """Every request: count it as activity, then check Host (blocks DNS rebinding)."""
        self.app.last_request = time.time()
        if self._host() not in ("localhost:%d" % self.app.port, "127.0.0.1:%d" % self.app.port):
            self._text(403, "Forbidden: this server only answers to 127.0.0.1:%d or localhost:%d.\n"
                       % (self.app.port, self.app.port))
            return None
        return urlsplit(self.path)

    def do_GET(self):
        u = self._begin()
        if u is None:
            return
        try:
            if u.path == "/api/health":
                return self._json(200, {"ok": True, "version": self.app.version,
                                        "port": self.app.port, "pid": os.getpid()})
            if u.path == "/api/settings":
                return self._json(200, settings.load(self.app.home))
            if u.path == "/api/review-source":
                return self._review_source(parse_qs(u.query).get("slug", [""])[0])
            if u.path.startswith("/review/") and u.path.endswith(".html"):
                return self._page(u.path[len("/review/"):-len(".html")])
            return self._text(404, "Not found.\n")
        except Exception:  # noqa: BLE001
            self.app.log("GET %s failed: %s" % (u.path, traceback.format_exc().strip().splitlines()[-1]))
            return self._text(500, "Internal error; see server.log in the review-doc folder.\n")

    MISSING = (
        "This review page does not exist, or it has expired.\n\n"
        "Pages are deleted %d hours after their last build (the stale-hours setting).\n"
        "The Markdown file behind it is never touched: render it again to get the page\n"
        "back, for example by asking Claude to review the file again.\n"
    )

    def _page(self, slug):
        path = self.app.page_path(slug)
        if path is None or not os.path.isfile(path):
            return self._text(404, self.MISSING % settings.load(self.app.home)["stale_hours"])
        self.app.freshen(slug, path)
        with io.open(path, encoding="utf-8") as fh:
            html = fh.read()
        return self._send(200, html, "text/html; charset=utf-8")

    def _review_source(self, slug):
        path = self.app.page_path(slug)
        src = source_of(pages.read_meta(path)) if path and os.path.isfile(path) else None
        if not src:
            return self._json(404, {"ok": False})
        # "page" lets a waiting page tell a re-render from Claude's first edit.
        try:
            built = int(os.path.getmtime(path) * 1000)
        except OSError:
            built = None
        return self._json(200, {"mtime": int(os.path.getmtime(src) * 1000), "page": built})

    def do_POST(self):
        u = self._begin()
        if u is None:
            return
        # The body is read before any refusal. On Windows, closing a socket while body
        # bytes are still arriving sends a reset, and the client never sees the answer.
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.close_connection = True
            return self._json(400, {"ok": False, "field": None, "error": "bad Content-Length"})
        if length > MAX_BODY:
            # Read it before answering: on Windows, closing a socket with unread data
            # sends a reset, and the client never sees the 413.
            left = min(length, 16 * MAX_BODY)
            while left > 0:
                chunk = self.rfile.read(min(left, 65536))
                if not chunk:
                    break
                left -= len(chunk)
            self.close_connection = True
            return self._json(413, {"ok": False, "field": None, "error": "body too large"})
        raw = self.rfile.read(length) if length > 0 else b""
        if u.path not in ("/api/settings", "/api/stop"):
            return self._text(404, "Not found.\n")
        if (self.headers.get("Origin") or "").strip().lower() != "http://" + self._host():
            return self._json(403, {"ok": False, "field": None, "error": "Origin must match the page"})
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return self._json(415, {"ok": False, "field": None, "error": "Content-Type must be application/json"})
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return self._json(400, {"ok": False, "field": None, "error": "body is not JSON"})
        if u.path == "/api/stop":
            self._json(200, {"ok": True})
            self.app.log("stop requested")
            self.app.stop()
            return
        try:
            return self._json(200, settings.apply(data, self.app.home))
        except settings.SettingError as exc:
            return self._json(400, {"ok": False, "field": exc.field, "error": str(exc)})


def main():
    if sys.stderr is None:  # pythonw has no streams at all
        sys.stderr = open(os.devnull, "w")
    srv = ReviewServer(ports=ports_from_env())
    try:
        code = srv.start()
        if code:
            return code
        srv.serve()
    except Exception:  # noqa: BLE001  stderr goes nowhere; the log is the only witness
        srv.log("server crashed: %s" % traceback.format_exc().strip().replace("\n", " | "))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
