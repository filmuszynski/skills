# -*- coding: utf-8 -*-
"""Run a ReviewServer inside the test process, and talk to it."""
import contextlib
import http.client
import json
import os
import sys
import threading

from harness import HERE

sys.path.insert(0, os.path.join(os.path.dirname(HERE), "server"))
import review_server  # noqa: E402


@contextlib.contextmanager
def serving(home, **kw):
    kw.setdefault("ports", [0])
    srv = review_server.ReviewServer(home=home, **kw)
    code = srv.start()
    assert code == 0, "start() returned %d" % code
    t = threading.Thread(target=srv.serve, daemon=True)
    t.start()
    srv.thread = t
    try:
        yield srv
    finally:
        srv.stop()
        t.join(5)


def request(srv, method, path, body=None, headers=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=15)
    h = {"Host": host if host is not None else "localhost:%d" % srv.port}
    h.update(headers or {})
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read()
    ctype = r.getheader("Content-Type") or ""
    conn.close()
    return r.status, ctype, data


def post_json(srv, path, obj, origin=True, headers=None):
    h = {"Content-Type": "application/json"}
    if origin is True:
        h["Origin"] = "http://localhost:%d" % srv.port
    elif origin:
        h["Origin"] = origin
    h.update(headers or {})
    body = obj if isinstance(obj, (str, bytes)) else json.dumps(obj)
    return request(srv, "POST", path, body=body, headers=h)
