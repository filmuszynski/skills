# -*- coding: utf-8 -*-
"""The draft number behind a page's At a glance box (1.1.5).

One record per page, ~/.review-doc/drafts/<slug>.json:

    {"draft": 3, "firstRendered": <epoch ms>, "pending": {"sourceMtime": <epoch ms>} | null}

The page sets `pending` through the server when Request changes is sent and clears
it on Cancel. A build counts up once, when a pending round meets a source newer
than the one the request was sent from; that is the page's own promoteRound test,
so the draft number and the earlier-round marks move together. Nothing else
counts: not the plan hook rendering on every edit, not the server's rebuild on
load, not a hand re-render.

It lives outside pages/ because a page is pruned after stale-hours and a review
that sits for four days must not come back as Draft 1.
"""
import io
import json
import os
import re
import tempfile
import time

import paths

SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+$")
KEEP_DAYS = 30


def drafts_dir(home=None):
    return os.path.join(home or paths.home_dir(), "drafts")


def _path(slug, home=None):
    if not SLUG_RE.match(slug or "") or slug.strip(".") == "":
        raise ValueError("invalid slug %r" % slug)
    return os.path.join(drafts_dir(home), slug + ".json")


def _now_ms():
    return int(time.time() * 1000)


def _fresh(now_ms=None):
    return {"draft": 1, "firstRendered": now_ms if now_ms is not None else _now_ms(), "pending": None}


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def load(slug, home=None):
    """The record, or None when there is none or it does not make sense."""
    try:
        with io.open(_path(slug, home), encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(rec, dict) or not _is_int(rec.get("draft")) or rec["draft"] < 1 \
            or not _is_int(rec.get("firstRendered")):
        return None
    p = rec.get("pending")
    pending = {"sourceMtime": p["sourceMtime"]} if isinstance(p, dict) and _is_int(p.get("sourceMtime")) else None
    return {"draft": rec["draft"], "firstRendered": rec["firstRendered"], "pending": pending}


def _save(slug, rec, home=None):
    target = _path(slug, home)
    folder = os.path.dirname(target)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".draft-", suffix=".tmp", dir=folder)
    try:
        with io.open(fd, "w", encoding="utf-8", newline="") as fh:
            json.dump(rec, fh)
        paths.replace(tmp, target)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def on_build(slug, source_mtime, home=None, now_ms=None):
    """Once per build, before rendering. Returns the record to show; never raises."""
    try:
        rec = load(slug, home)
        if rec is None:
            rec = _fresh(now_ms)
            _save(slug, rec, home)
            return rec
        p = rec["pending"]
        if p and source_mtime > p["sourceMtime"]:
            rec["draft"] += 1
            rec["pending"] = None
            _save(slug, rec, home)
        return rec
    except Exception:  # noqa: BLE001  a broken record costs a number, never a page
        return _fresh(now_ms)


def request(slug, source_mtime, home=None, now_ms=None):
    """Request changes was sent from a page built on source_mtime. Raises ValueError on a bad slug."""
    _path(slug, home)
    rec = load(slug, home) or _fresh(now_ms)
    rec["pending"] = {"sourceMtime": int(source_mtime)}
    _save(slug, rec, home)
    return rec


def cancel(slug, home=None):
    """The request was taken back. None when there is no record to change."""
    _path(slug, home)
    rec = load(slug, home)
    if rec is None:
        return None
    if rec["pending"] is not None:
        rec["pending"] = None
        _save(slug, rec, home)
    return rec


def prune(home=None, now=None):
    """Delete records whose page is gone and that were last written KEEP_DAYS ago."""
    home = home or paths.home_dir()
    d = drafts_dir(home)
    cutoff = (now if now is not None else time.time()) - KEEP_DAYS * 86400
    gone = 0
    try:
        names = os.listdir(d)
    except OSError:
        return 0
    for n in names:
        if not n.endswith(".json"):
            continue
        p = os.path.join(d, n)
        try:
            if os.path.isfile(os.path.join(home, "pages", n[:-5] + ".html")):
                continue
            if os.path.getmtime(p) < cutoff:
                os.remove(p)
                gone += 1
        except OSError:
            pass
    return gone


def created(source_path, rec, stat=os.stat, nt=None):
    """("Created", ms) where the file system records a creation time, else the first
    render under its own name. Linux keeps none, and a time is never shown under a
    label it does not mean."""
    nt = (os.name == "nt") if nt is None else nt
    try:
        st = stat(source_path)
        birth = getattr(st, "st_birthtime", None)
        if birth:
            return ("Created", int(birth * 1000))
        if nt:
            return ("Created", int(st.st_ctime * 1000))   # creation time on Windows
    except OSError:
        pass
    return ("First reviewed", rec["firstRendered"])


def fmt(ms):
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(ms / 1000.0))


def facts(rec, source_path, source_mtime):
    """The three rows the At a glance box ends with."""
    label, ms = created(source_path, rec)
    return [("Draft", str(rec["draft"])), (label, fmt(ms)), ("Last edited", fmt(source_mtime))]
