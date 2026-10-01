# -*- coding: utf-8 -*-
"""Render a planning artifact as a reviewable HTML page.

    python presenter/build_screen.py plan   .claude/plans/some-plan.md
    python presenter/build_screen.py screen screens/pick.md
    python presenter/build_screen.py doc    notes/meeting.md
    python presenter/build_screen.py html   site/index.html

Prints one JSON object on stdout so the hook can quote the link back without
parsing prose. Exits non-zero only on a real failure; the caller decides how
loud that should be.

Exit codes: 0 rendered, 1 missing or unwritable file, 2 bad arguments, 3 the page type
is switched off, 4 a file type review-doc does not review, 5 an HTML page and no review server to serve it.
"""
from __future__ import print_function, unicode_literals

import argparse
import datetime
import hashlib
import io
import json
import os
import pathlib
import re
import sys
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import drafts  # noqa: E402
import layout_doc  # noqa: E402
import layout_html  # noqa: E402
import layout_plan  # noqa: E402
import layout_screen  # noqa: E402
import shell  # noqa: E402
import paths  # noqa: E402
import pages  # noqa: E402
import settings  # noqa: E402
import launch  # noqa: E402
import opening  # noqa: E402
import extension  # noqa: E402


def _read(path):
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


# kind (CLI subcommand) -> the settings switch that allows it. Plans are gated by the
# hook (Phase 4), not here, so a plan can always be rendered by hand.
SWITCH = {"doc": "md", "screen": "choice", "html": "html"}


class Disabled(Exception):
    def __init__(self, setting):
        Exception.__init__(self, setting)
        self.setting = setting


MARKDOWN = (".md", ".markdown")
HTML = (".html", ".htm")
SUPPORTED = "review-doc reviews Markdown files (.md, .markdown) and HTML pages (.html, .htm)."
LOCAL_ONLY = "HTML review opens local files and localhost only."
# Proxy mode (1.2 Phase 5) replaces this refusal with the real thing.
NO_PROXY_YET = "Reviewing a running localhost dev server is not built yet."
LOOPBACK = ("localhost", "127.0.0.1", "::1")
URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


class Unsupported(Exception):
    """A file this version cannot review. The message is for the user, as is."""
    def __init__(self, message):
        Exception.__init__(self, message)
        self.message = message


def check_type(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in MARKDOWN:
        return
    if ext in HTML:
        raise Unsupported("HTML pages are reviewed with the html kind: build_screen.py html <file>.")
    raise Unsupported(SUPPORTED)


def is_url(target):
    return bool(URL_RE.match(target or ""))


def check_html(target, slug=None):
    """Everything that can refuse an HTML render, checked before a server is started
    or a page written: the target, the slug, the setting."""
    if is_url(target):
        try:
            u = urlsplit(target)
            host = u.hostname or ""
        except ValueError:
            raise Unsupported(LOCAL_ONLY)
        if u.scheme.lower() in ("http", "https") and host in LOOPBACK:
            raise Unsupported(NO_PROXY_YET)
        raise Unsupported(LOCAL_ONLY)
    if os.path.splitext(target)[1].lower() not in HTML:
        raise Unsupported(SUPPORTED)
    if slug is not None and not pages.HTML_SLUG_RE.match(slug):
        raise ValueError("invalid slug %r for an HTML page: lowercase letters, digits and hyphens, "
                         "at most 63, no hyphen at either end" % slug)
    if not settings.kind_enabled("html"):
        raise Disabled("html")


def html_slug(path):
    """Parent folder plus file name, as for documents, but a DNS label: the slug is
    also the frame's host name, <slug>.localhost."""
    parts = [p for p in _norm(path).split("/") if p]
    stem = re.sub(r"\.html?$", "", parts[-1], flags=re.I) if parts else "page"
    base = (parts[-2] + "-" + stem) if len(parts) > 1 else stem
    base = base.encode("ascii", "ignore").decode("ascii").lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:50].strip("-") or "page"
    return base + "-" + source_hash(path)


def _norm(path):
    p = os.path.normcase(os.path.realpath(os.path.abspath(path)))
    return p.replace("\\", "/")


def source_hash(path):
    return hashlib.sha1(_norm(path).encode("utf-8")).hexdigest()[:6]


# What an explicit --slug may contain. Anything else could name a file outside pages/.
SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def default_slug(kind, path):
    # Named from the normalised path, like the hash, so `notes.md`, `./notes.md` and the
    # absolute path are one page, not two.
    norm = _norm(path)
    base = layout_doc.slug_for_path(norm) if kind == "doc" else layout_plan.slug_for(norm)
    base = base.encode("ascii", "ignore").decode("ascii").strip("-") or kind
    return base + "-" + source_hash(path)


LAYOUTS = {"plan": layout_plan, "screen": layout_screen, "doc": layout_doc}


def build(kind, md_path, slug=None, out_dir=None):
    """Render one Markdown file with the layout that matches its kind.

    The three differ only in which module parses the Markdown; everything after
    that, the shell, the target path and the reported link, is the same job.
    """
    if kind == "html":
        return build_html(md_path, slug=slug, out_dir=out_dir)
    check_type(md_path)
    if slug is not None and (not SLUG_RE.match(slug) or slug.strip(".") == ""):
        raise ValueError("invalid slug %r: use letters, digits, dot, dash, underscore" % slug)
    sw = SWITCH.get(kind)
    if sw and not settings.kind_enabled(sw):
        raise Disabled(sw)
    raw = _read(md_path)
    source = os.path.abspath(md_path).replace("\\", "/")
    slug = slug or default_slug(kind, md_path)
    # The source's own time, in epoch milliseconds so no time zone can skew the
    # comparison. The page asks the server for the current value and shows a
    # banner when it has moved on; the server rebuilds a page whose source did.
    source_mtime = int(os.path.getmtime(md_path) * 1000)
    extra = {}
    if kind in ("plan", "doc"):
        # Draft, Created, Last edited (1.1.5). The record counts a round once its
        # request meets a newer source; see drafts.py.
        extra["facts"] = drafts.facts(drafts.on_build(slug, source_mtime), md_path, source_mtime)
    built = LAYOUTS[kind].build(
        raw,
        source=source,
        slug=slug,
        generated_at=datetime.datetime.now().replace(microsecond=0).isoformat(),
        **extra
    )
    built["meta"]["sourceMtime"] = source_mtime
    built["meta"]["version"] = paths.version()
    return _write(built, source, out_dir)


def _write(built, source, out_dir):
    """Render the shell page and write it to pages/ (or --out); the result for the caller."""
    html = shell.render(**built)
    folder = os.path.realpath(out_dir or paths.pages_dir())
    target = os.path.join(folder, built["meta"]["slug"] + ".html")
    if os.path.dirname(os.path.realpath(target)) != folder:
        raise ValueError("page would be written outside %s" % folder)
    existed = os.path.exists(target)
    shell.write(target, html)
    if out_dir is None:
        pages.prune()  # an explicit --out folder is never pruned
    return {
        "ok": True,
        # A screen reports options or explain, not "screen": the kind the reader
        # sees is the one the layout chose.
        "kind": built["meta"]["kind"],
        "slug": built["meta"]["slug"],
        "title": built["title"],
        "source": source,
        "path": os.path.abspath(target).replace("\\", "/"),
        # file:// here; main() swaps in the server link when a server answers.
        "url": pathlib.Path(target).resolve().as_uri(),
        "sections": len(built["sections"]),
        "server": False,
        # Whether this render created the page, rather than refreshing one: only a
        # new page is opened automatically.
        "new": not existed,
    }


def build_html(path, slug=None, out_dir=None):
    """Render the review page for a local HTML file. The page is the frame page; the
    file itself reaches the frame through the review server's frame listener."""
    check_html(path, slug)
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()  # only the <title> is read from it
    source = os.path.abspath(path).replace("\\", "/")
    built = layout_html.build(
        raw,
        source=source,
        slug=slug or html_slug(path),
        generated_at=datetime.datetime.now().replace(microsecond=0).isoformat(),
    )
    built["meta"]["sourceMtime"] = int(os.path.getmtime(path) * 1000)
    built["meta"]["version"] = paths.version()
    return _write(built, source, out_dir)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="kind")
    for kind, text in (("plan", "render a plan Markdown file"),
                       ("screen", "render an options or explainer screen"),
                       ("doc", "render a prose document for review"),
                       ("html", "render a local HTML page for review")):
        p = sub.add_parser(kind, help=text)
        p.add_argument("path")
        p.add_argument("--slug", default=None)
        p.add_argument("--out", default=None, help="output directory (never served, never pruned)")
        p.add_argument("--no-open", action="store_true",
                       help="do not open the page, whatever the auto-open setting says")
        p.add_argument("--no-server", action="store_true",
                       help="do not start or use the local server")

    args = ap.parse_args(argv)
    if args.kind not in LAYOUTS and args.kind != "html":
        ap.print_help(sys.stderr)
        return 2

    html_kind = args.kind == "html"
    # A URL is refused by check_html with its own message, not as a missing file.
    if not (html_kind and is_url(args.path)) and not os.path.isfile(args.path):
        print(json.dumps({"ok": False, "error": "no such file: " + args.path}))
        return 1
    if html_kind and args.out is not None:
        print(json.dumps({"ok": False, "error": "--out is not supported for html: "
                                                "the page is served by the review server"}))
        return 2

    port = None
    try:
        if html_kind:
            check_html(args.path, args.slug)
            # An HTML page cannot fall back to file://: it needs the frame origin.
            port, why = (None, "--no-server was given") if args.no_server else launch.ensure_server()
            if not port:
                print(json.dumps({"ok": False, "reason": "needs-server",
                                  "message": "HTML review needs the local review server: %s" % why}))
                return 5
        result = build(args.kind, args.path, slug=args.slug, out_dir=args.out)
    except Unsupported as exc:
        print(json.dumps({"ok": False, "reason": "unsupported", "message": exc.message}))
        return 4
    except Disabled as exc:
        print(json.dumps({"ok": False, "reason": "disabled", "setting": exc.setting}))
        return 3
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    except OSError as exc:
        # A locked or unwritable page, for example: still one JSON line for the caller.
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    # A page written to --out lives outside pages/, where no server could find it.
    if port:
        result["url"] = "http://127.0.0.1:%d/review/%s.html" % (port, result["slug"])
        result["server"] = True
    elif args.out is None and not args.no_server:
        port, why = launch.ensure_server()
        if port:
            result["url"] = "http://127.0.0.1:%d/review/%s.html" % (port, result["slug"])
            result["server"] = True
        else:
            result["serverNote"] = why
    result["opened"] = False
    if (result["new"] and not args.no_open and not os.environ.get("REVIEW_DOC_NO_OPEN")
            and settings.load()["auto_open"]):
        result["opened"] = opening.open_page(result["url"])
    try:
        # Only with a new page: an edit of a page already handed over must not ask again.
        result["offerExtension"] = bool(result["new"]) and extension.should_offer()
    except Exception:  # noqa: BLE001  (an offer is a nicety; it never fails a render)
        result["offerExtension"] = False
    # ASCII on purpose: a shell pipe on Windows uses the ANSI code page, which has no
    # letter for many titles and paths. Every JSON reader decodes the escapes.
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
