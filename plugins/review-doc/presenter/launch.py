# -*- coding: utf-8 -*-
"""Make sure the review server is running, and find its port.

ensure_server() answers (port, None) when a server of this version answers for this
home folder, and (None, reason) otherwise, so the caller can fall back to file://.
"""
import io
import json
import os
import subprocess
import sys
import time
import urllib.request

import paths

WAIT = 3.0
HEALTH_TIMEOUT = 0.5
SERVER = os.path.join(paths.plugin_root(), "server", "review_server.py")
# Localhost never goes through a proxy. Without this, HTTP_PROXY on a company
# machine sends every health check to the proxy and a new server starts per render.
OPENER_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _log_path(home):
    return os.path.join(home, "server.log")


def read_info(home=None):
    try:
        with io.open(os.path.join(home or paths.home_dir(), "server.json"), encoding="utf-8") as fh:
            info = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict):
        return None
    port = info.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536:
        return None
    return info


def health(port, timeout=HEALTH_TIMEOUT):
    """The server's health answer, or None if nothing, or something else, answers."""
    try:
        with OPENER_NO_PROXY.open("http://127.0.0.1:%d/api/health" % port, timeout=timeout) as r:
            got = json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001  refused, timed out, not JSON: all mean "not ours"
        return None
    if isinstance(got, dict) and got.get("ok") is True and got.get("port") == port:
        return got
    return None


def stop(port, wait=2.0):
    """Ask the server on port to stop. True once it no longer answers."""
    req = urllib.request.Request(
        "http://127.0.0.1:%d/api/stop" % port, data=b"{}", method="POST",
        headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:%d" % port})
    try:
        OPENER_NO_PROXY.open(req, timeout=HEALTH_TIMEOUT).read()
    except Exception:  # noqa: BLE001
        pass
    deadline = time.time() + wait
    while time.time() < deadline:
        if health(port, 0.2) is None:
            return True
        time.sleep(0.1)
    return False


def interpreter():
    """pythonw.exe next to this Python on Windows, so no console window appears."""
    exe = sys.executable
    if os.name == "nt":
        w = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.isfile(w):
            return w
    return exe


def spawn(home=None):
    home = home or paths.home_dir()
    os.makedirs(home, exist_ok=True)
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              close_fds=True,
              # Not the user's project folder: on Windows a live process's working
              # directory cannot be deleted or renamed.
              cwd=home, env=dict(os.environ, REVIEW_DOC_HOME=home))
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen([interpreter(), SERVER], **kw)


def _ours(info):
    """The health answer if the server in server.json is really the one answering."""
    got = health(info["port"])
    if got and got.get("pid") == info.get("pid"):
        return got
    return None


def _last_log_line(home):
    try:
        with io.open(_log_path(home), encoding="utf-8") as fh:
            lines = [ln.strip() for ln in fh if ln.strip()]
        return lines[-1] if lines else ""
    except OSError:
        return ""


def version_key(v):
    """Sortable form of a version: 0.1.0-dev < 0.1.0 < 0.1.1. Unparseable sorts first."""
    main, _, pre = str(v).partition("-")
    try:
        nums = tuple(int(p) for p in main.split("."))
    except ValueError:
        return ((-1,), 0)
    return (nums, 0 if pre else 1)


def ensure_server(home=None, wait=WAIT):
    if os.environ.get("REVIEW_DOC_NO_SERVER"):
        return None, "server disabled by REVIEW_DOC_NO_SERVER"
    home = home or paths.home_dir()
    mine = version_key(paths.version())

    def usable(got):
        # Same or newer: serve from it. Only an older one is replaced, so two sessions
        # on different versions (one not yet reloaded) do not stop each other in turn.
        return got is not None and version_key(got.get("version")) >= mine

    info = read_info(home)
    if info:
        got = _ours(info)
        if usable(got):
            return info["port"], None
        if got:
            # An older plugin's server: stop it so this version serves.
            stop(info["port"])
    try:
        spawn(home)
    except OSError as exc:
        return None, "could not start the review server: %s" % exc
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(0.1)
        info = read_info(home)
        if info:
            if usable(_ours(info)):
                return info["port"], None
    last = _last_log_line(home)
    why = "the review server did not answer within %g seconds" % wait
    if last:
        why += " (%s)" % last
    return None, why + "; details in %s" % _log_path(home)
