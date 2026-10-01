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
import os
import re
from urllib.parse import unquote

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
# What may come before the probe when there is no <head>: a BOM, comments, the
# doctype and the <html> start tag. A script before the doctype means quirks mode.
_LEAD_RE = re.compile(r"\A\ufeff?(?:\s*(?:<!--.*?-->\s*)*<!doctype[^>]*>)?"
                      r"(?:\s*(?:<!--.*?-->\s*)*<html(?=[\s>])[^>]*>)?", re.I | re.S)


def probe_tag(nonce):
    return '<script src="%s" nonce="%s"></script>' % (PROBE_PATH, nonce)


def inject_probe(text, nonce):
    """The probe tag right after <head>, or after the doctype and <html> without one."""
    tag = probe_tag(nonce)
    m = _HEAD_RE.search(text)
    cut = m.end() if m else _LEAD_RE.match(text).end()
    return text[:cut] + tag + text[cut:]


def rewrite_html(data, nonce):
    """An HTML file's bytes with the CSP taught the nonce and the probe tag added.
    UTF-8 when it decodes as such; otherwise byte for byte through latin-1, and the
    page's own <meta charset> decides, as it would without us."""
    try:
        text, enc, ctype = data.decode("utf-8"), "utf-8", "text/html; charset=utf-8"
    except UnicodeDecodeError:
        text, enc, ctype = data.decode("latin-1"), "latin-1", "text/html"
    return inject_probe(rewrite_meta_csp(text, nonce), nonce).encode(enc), ctype


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
    TYPES. A directory serves its index.html."""
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
        # The index file may itself be a link: judge the file it really is.
        target = os.path.realpath(os.path.join(target, "index.html"))
        if not _inside(real_root, target):
            return None
        if _hidden(os.path.relpath(target, real_root).replace("\\", "/").split("/")):
            return None
    if os.path.splitext(target)[1].lower() not in TYPES or not os.path.isfile(target):
        return None
    return target


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
