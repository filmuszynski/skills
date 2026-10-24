# -*- coding: utf-8 -*-
"""The frame listener: the page under review, on an origin of its own (1.2).

Every HTML review is served at http://<slug>.localhost:<frame port>/, where the
frame port is the review server's port + 100 (ADR 0016). In file mode the folder
of the reviewed file is served read-only. Every HTML response gets the probe
script, with a fresh nonce that the page's Content-Security-Policy is taught to
accept. Phase 0 findings: docs/spikes/2026-10-01-html-review-phase-0-findings.md.

This module holds the pure parts and the request handler; review_server.py owns
the sockets.
"""
from __future__ import print_function

import html as _html
import http.server
import os
import re
import secrets
import time
import traceback
from urllib.parse import quote, unquote, urlsplit

import charset
import pages

FRAME_OFFSET = 100
PROBE_PATH = "/__review-doc/probe.js"
RESERVED = "/__review-doc/"
PROBE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "presenter", "assets", "probe.js")

# The only files file mode serves. No charset on text types: the browser takes it
# from a BOM, an @charset rule or the page, as it would from any static server.
TYPES = {
    ".html": "text/html", ".htm": "text/html",
    ".css": "text/css",
    ".js": "text/javascript", ".mjs": "text/javascript",
    ".json": "application/json", ".map": "application/json",
    ".wasm": "application/wasm",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".webp": "image/webp", ".avif": "image/avif", ".ico": "image/x-icon", ".svg": "image/svg+xml",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf",
    ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".wav": "audio/wav",
    ".mp4": "video/mp4", ".webm": "video/webm",
}
HTML_EXT = (".html", ".htm")

# ------------------------------------------------------------------ CSP

_KEYED = ("'nonce-", "'sha256-", "'sha384-", "'sha512-")


def _allow_probe(directive, nonce):
    """One script directive, changed so the probe may run and the page's own scripts
    still do."""
    lead = directive[:len(directive) - len(directive.lstrip())]
    tokens = directive.split()
    name = tokens[0]
    # 'none' next to another source is an invalid list; replace it, never combine.
    sources = [t for t in tokens[1:] if t.lower() != "'none'"]
    low = [t.lower() for t in sources]
    keyed = any(t.startswith(_KEYED) for t in low)
    if "'unsafe-inline'" in low and not keyed and "'strict-dynamic'" not in low:
        # A nonce here would switch 'unsafe-inline' off and stop the page's own
        # inline scripts. The probe is a file from this origin: 'self' admits it.
        if "'self'" not in low:
            sources.append("'self'")
    else:
        sources.append("'nonce-%s'" % nonce)
    return lead + " ".join([name] + sources)


def _one_policy(policy, nonce):
    dirs = policy.split(";")
    names = [(d.split(None, 1)[0].lower() if d.strip() else "") for d in dirs]
    targets = [n for n in ("script-src-elem", "script-src") if n in names]
    if not targets and "default-src" in names:
        targets = ["default-src"]
    for i, n in enumerate(names):
        # Browsers honour only the first of a repeated directive.
        if n in targets and names.index(n) == i:
            dirs[i] = _allow_probe(dirs[i], nonce)
    return ";".join(dirs)


def add_nonce(policy, nonce):
    """A CSP header value or <meta> content, with the probe allowed to run. A comma
    separates whole policies; each is enforced on its own, so each is changed."""
    return ",".join(_one_policy(p, nonce) for p in policy.split(","))


_META_RE = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR = r"""\b%s\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))"""


def _attr(tag, name):
    return re.search(_ATTR % name, tag, re.I)


def _value(m):
    return next(g for g in m.groups() if g is not None)


def rewrite_meta_csp(text, nonce):
    """Every <meta http-equiv="Content-Security-Policy"> gets the nonce. The value is
    read whatever its quote (a policy is full of single quotes, which is how the
    Phase 0 spike's first regex broke) and written back double-quoted."""
    def fix(m):
        tag = m.group(0)
        eq = _attr(tag, "http-equiv")
        if not eq or _value(eq).strip().lower() != "content-security-policy":
            return tag
        c = _attr(tag, "content")
        if not c:
            return tag
        new = add_nonce(_html.unescape(_value(c)), nonce)
        new = new.replace("&", "&amp;").replace('"', "&quot;")
        return tag[:c.start()] + 'content="' + new + '"' + tag[c.end():]
    return _META_RE.sub(fix, text)


# ------------------------------------------------------------------ the probe tag

_HEAD_RE = re.compile(r"<head(?=[\s>/])[^>]*>", re.I)
# Spans whose text is not markup. An unclosed one runs to the end of the file.
_OPAQUE_RE = re.compile(r"<!--.*?(?:-->|\Z)"
                        r"|<script(?=[\s>/])[^>]*>.*?(?:</script\s*>|\Z)"
                        r"|<style(?=[\s>/])[^>]*>.*?(?:</style\s*>|\Z)", re.I | re.S)
# What may come before the probe when there is no <head>: a BOM, comments, the
# doctype and the <html> start tag. A script before the doctype means quirks mode.
_LEAD_RE = re.compile(r"\A\ufeff?(?:\s*(?:<!--.*?-->\s*)*<!doctype[^>]*>)?"
                      r"(?:\s*(?:<!--.*?-->\s*)*<html(?=[\s>])[^>]*>)?", re.I | re.S)


def probe_tag(nonce):
    return '<script src="%s" nonce="%s"></script>' % (PROBE_PATH, nonce)


def _first_real_head(text):
    """The first <head> start tag that is markup, not text inside a comment, a
    script or a style (a page may well write "<head>" in a string)."""
    hidden = [s.span() for s in _OPAQUE_RE.finditer(text)]
    for m in _HEAD_RE.finditer(text):
        if not any(a <= m.start() < b for a, b in hidden):
            return m
    return None


def inject_probe(text, nonce):
    """The probe tag right after <head>, or after the doctype and <html> without one."""
    tag = probe_tag(nonce)
    m = _first_real_head(text)
    cut = m.end() if m else _LEAD_RE.match(text).end()
    return text[:cut] + tag + text[cut:]


def rewrite_html(data, nonce):
    """An HTML file's bytes with the CSP taught the nonce and the probe tag added,
    in the file's own encoding (charset.sniff) with its BOM kept first. Bytes that
    do not decode in it go through byte for byte as latin-1, and the browser decides."""
    enc, bom = charset.sniff(data)
    try:
        text, ctype = data[bom:].decode(enc), "text/html; charset=%s" % enc
    except UnicodeDecodeError:
        text, enc, ctype = data[bom:].decode("latin-1"), "latin-1", "text/html"
    body = inject_probe(rewrite_meta_csp(text, nonce), nonce)
    return data[:bom] + body.encode(enc), ctype


# ------------------------------------------------------------------ paths

def _inside(root, path):
    r, p = os.path.normcase(root), os.path.normcase(path)
    try:
        return os.path.commonpath([r, p]) == r
    except ValueError:  # another drive on Windows
        return False


def _hidden(parts):
    return any(p.startswith(".") for p in parts)


def resolve(root, url_path):
    """The file a request path names inside root, or None.

    None for anything outside root (symlinks and junctions resolved), any part that
    starts with a dot (so .env and .git never leak), a backslash, a colon (drive
    letters, Windows streams), a NUL, bad percent-encoding, and any type outside
    TYPES. A directory path that ends in / serves its index.html; without the
    slash it is None, and the handler redirects it (see needs_slash)."""
    try:
        path = unquote(url_path or "", errors="strict")
    except UnicodeDecodeError:
        return None
    if not path.startswith("/") or "\x00" in path or "\\" in path or ":" in path:
        return None
    parts = [p for p in path.split("/") if p]
    if not parts or _hidden(parts):
        return None
    real_root = os.path.realpath(root)
    target = os.path.realpath(os.path.join(real_root, *parts))
    if not _inside(real_root, target) or target == real_root:
        return None
    if _hidden(os.path.relpath(target, real_root).replace("\\", "/").split("/")):
        return None
    if os.path.isdir(target):
        if not path.endswith("/"):
            # Served here, the index file's relative links would resolve against
            # the parent folder.
            return None
        # The index file may itself be a link: judge the file it really is.
        target = os.path.realpath(os.path.join(target, "index.html"))
        if not _inside(real_root, target):
            return None
        if _hidden(os.path.relpath(target, real_root).replace("\\", "/").split("/")):
            return None
    elif path.endswith("/"):
        return None  # a file is never a folder: /index.html/ is not /index.html
    if os.path.splitext(target)[1].lower() not in TYPES or not os.path.isfile(target):
        return None
    return target


def needs_slash(root, url_path):
    """True when url_path names a directory without its trailing slash, and the
    slashed path is one resolve() serves. Judged by resolve itself, so a redirect
    never confirms anything resolve would refuse (a dot folder, a link out)."""
    if not url_path or url_path.endswith("/"):
        return False
    try:
        if unquote(url_path, errors="strict").endswith("/"):
            return False
    except UnicodeDecodeError:
        return False
    return resolve(root, url_path + "/") is not None


def file_target(meta):
    """{root, entry} of an HTML page in file mode, or None for any other page."""
    if not isinstance(meta, dict) or meta.get("kind") != "html":
        return None
    t = meta.get("target")
    if not isinstance(t, dict) or t.get("type") != "file":
        return None
    root, entry = t.get("root"), t.get("entry")
    if not isinstance(root, str) or not os.path.isabs(root) or not os.path.isdir(root):
        return None
    if (not isinstance(entry, str) or not entry or entry.startswith(".")
            or "/" in entry or "\\" in entry):
        return None
    return {"root": root, "entry": entry}


# ------------------------------------------------------------------ ranges

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def parse_range(header, size):
    """(start, end) of one byte range, None to send the whole file (no header, a
    list of ranges, another unit), or "bad" for a 416."""
    m = _RANGE_RE.match((header or "").strip())
    if not m or (m.group(1) == "" and m.group(2) == ""):
        return None
    if size == 0:
        return "bad"
    if m.group(1) == "":
        n = int(m.group(2))
        return "bad" if n == 0 else (max(0, size - n), size - 1)
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else size - 1
    if start >= size or end < start:
        return "bad"
    return (start, min(end, size - 1))


# ------------------------------------------------------------------ the handler

class FrameHandler(http.server.BaseHTTPRequestHandler):
    """One request to <slug>.localhost:<frame port>. Read-only: GET and HEAD."""
    server_version = "review-doc"

    def log_message(self, fmt, *args):
        pass  # requests are not logged; errors go to server.log through app.log

    @property
    def app(self):
        return self.server.app

    def _plain(self, code, text, headers=()):
        data = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _slug(self):
        """The review this request is for, from its Host header, or None."""
        host = (self.headers.get("Host") or "").strip().lower()
        tail = ".localhost:%d" % self.app.frame_port
        if not host.endswith(tail):
            return None
        slug = host[:-len(tail)]
        return slug if pages.HTML_SLUG_RE.match(slug) else None

    def do_GET(self):
        self._serve()

    def do_HEAD(self):
        self._serve()

    def _not_allowed(self):
        # Read the body first: on Windows, closing with unread bytes sends a reset
        # and the client never sees the answer.
        try:
            left = min(int(self.headers.get("Content-Length") or 0), 1 << 20)
        except ValueError:
            left = 0
        while left > 0:
            chunk = self.rfile.read(min(left, 65536))
            if not chunk:
                break
            left -= len(chunk)
        self.close_connection = True
        self._plain(405, "Method not allowed: the review frame is read-only.\n", [("Allow", "GET, HEAD")])

    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _not_allowed

    def _serve(self):
        slug = self._slug()
        target = self.app.frame_target(slug) if slug else None
        if target is None:
            # Not activity: any web page can send these, and they must not keep
            # the server alive.
            return self._plain(403, "Forbidden: no HTML review answers to this name.\n")
        self.app.last_request = time.time()
        u = urlsplit(self.path)
        path = u.path or "/"
        self._sent = False
        try:
            return self._file_mode(slug, target, path, u.query)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return None  # the browser went away mid-file (a video seek, a reload)
        except Exception:  # noqa: BLE001
            self.app.log("frame %s %s failed: %s"
                         % (slug, path, traceback.format_exc().strip().splitlines()[-1]))
            if self._sent:
                # Headers are out: a second response would corrupt the stream.
                self.close_connection = True
                return None
            return self._plain(500, "Internal error; see server.log in the review-doc folder.\n")

    def _file_mode(self, slug, target, path, query=""):
        if path == PROBE_PATH:
            return self._probe()
        if path.startswith(RESERVED):
            return self._plain(404, "Not found.\n")
        file = resolve(target["root"], "/" + quote(target["entry"]) if path == "/" else path)
        if file is None:
            if needs_slash(target["root"], path):
                # One leading slash: //host/... would be a link to another site.
                loc = "/" + path.lstrip("/") + "/" + ("?" + query if query else "")
                return self._plain(301, "Moved: %s\n" % loc, [("Location", loc)])
            return self._plain(404, "Not found.\n")
        self.app.note_served(slug, file)
        if os.path.splitext(file)[1].lower() in HTML_EXT:
            return self._html(file)
        return self._file(file)

    def _head(self, code, ctype, length, extra=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        # Every reload shows the file as it is now, never a cached copy.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        # Defence in depth: no other origin may load the site's files.
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self._sent = True

    def _probe(self):
        with open(PROBE_FILE, "rb") as fh:
            data = fh.read()
        self._head(200, "text/javascript; charset=utf-8", len(data))
        if self.command != "HEAD":
            self.wfile.write(data)

    def _html(self, file):
        with open(file, "rb") as fh:
            raw = fh.read()
        data, ctype = rewrite_html(raw, secrets.token_hex(16))
        # Our own policy, a header of its own: only the review page may frame the
        # site. Browsers enforce it beside the page's <meta> policy, never merged.
        main = self.app.frame_port - FRAME_OFFSET
        self._head(200, ctype, len(data), [(
            "Content-Security-Policy",
            "frame-ancestors http://127.0.0.1:%d http://localhost:%d" % (main, main))])
        if self.command != "HEAD":
            self.wfile.write(data)

    def _file(self, file):
        size = os.path.getsize(file)
        rng = parse_range(self.headers.get("Range"), size)
        if rng == "bad":
            return self._plain(416, "Range not satisfiable.\n", [("Content-Range", "bytes */%d" % size)])
        start, end = rng or (0, size - 1)
        extra = [("Accept-Ranges", "bytes")]
        if rng:
            extra.append(("Content-Range", "bytes %d-%d/%d" % (start, end, size)))
        self._head(206 if rng else 200, TYPES[os.path.splitext(file)[1].lower()], end - start + 1, extra)
        if self.command == "HEAD":
            return
        with open(file, "rb") as fh:
            fh.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = fh.read(min(left, 65536))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)
