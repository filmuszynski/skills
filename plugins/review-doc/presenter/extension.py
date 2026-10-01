# -*- coding: utf-8 -*-
"""The VS Code opener extension: whether to offer it, and installing it.

    python presenter/extension.py status
    python presenter/extension.py install [--vsix FILE]
    python presenter/extension.py decline

Each prints one JSON line. install and decline both record that the question was
answered (vscode_asked in config.json), so the offer is made once.
"""
from __future__ import print_function

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opening  # noqa: E402
import paths  # noqa: E402
import settings  # noqa: E402

RELEASE_URL = "https://github.com/filmuszynski/skills/releases/download/v%s/review-doc-opener.vsix"
RELOAD_HINT = ("New review pages open in VS Code's built-in browser. If one still opens in "
               "the system browser, run Developer: Reload Window once.")


def status(home=None):
    terminal = os.environ.get("TERM_PROGRAM") == "vscode"
    code = bool(shutil.which("code"))
    installed = opening.extension_installed()
    asked = bool(settings.load(home)["vscode_asked"])
    return {"vscodeTerminal": terminal, "code": code, "installed": installed, "asked": asked,
            "offer": terminal and code and not installed and not asked}


def should_offer(home=None):
    return status(home)["offer"]


def _mark_asked(home=None):
    cfg = settings.load(home)
    cfg["vscode_asked"] = True
    settings.save(cfg, home)


def release_url(version=None):
    v = version or paths.version()
    return None if "-" in v else RELEASE_URL % v


def _download(url, home=None):
    folder = home or paths.home_dir()
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="opener-", suffix=".vsix", dir=folder)
    try:
        with os.fdopen(fd, "wb") as out:
            resp = urllib.request.urlopen(url, timeout=30)
            with resp:
                shutil.copyfileobj(resp, out)
    except Exception:
        os.remove(tmp)
        raise
    return tmp


def decline(home=None):
    _mark_asked(home)
    return {"ok": True, "message": "Understood. Pages keep opening in the system browser."}


def install(vsix=None, home=None):
    # Answered either way: a failure below is reported once, not asked again.
    _mark_asked(home)
    code = shutil.which("code")
    if not code:
        return {"ok": False, "message": "The code command is not on PATH. In VS Code, run "
                "Shell Command: Install 'code' command in PATH, then ask again."}
    downloaded = None
    if vsix is None:
        url = release_url()
        if url is None:
            return {"ok": False, "message": "This is a development version (%s) with no release "
                    "to download from. Build the extension and pass --vsix <file>." % paths.version()}
        try:
            vsix = downloaded = _download(url, home)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": "Could not download the extension from %s (%s). To "
                    "install it by hand, download that file and run: code --install-extension "
                    "<file>" % (url, exc)}
    elif not os.path.isfile(vsix):
        return {"ok": False, "message": "No such file: %s" % vsix}
    try:
        r = subprocess.run([code, "--install-extension", vsix, "--force"],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "message": "code --install-extension did not run: %s" % exc}
    finally:
        if downloaded and os.path.exists(downloaded):
            os.remove(downloaded)
    if r.returncode != 0:
        said = ((r.stderr or "") + (r.stdout or "")).strip()[-300:]
        return {"ok": False, "message": "code --install-extension failed: %s" % said}
    return {"ok": True, "message": "Installed. " + RELOAD_HINT}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status")
    p = sub.add_parser("install")
    p.add_argument("--vsix", default=None)
    sub.add_parser("decline")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    if args.cmd == "status":
        print(json.dumps(status()))
        return 0
    if args.cmd == "install":
        res = install(vsix=args.vsix)
    elif args.cmd == "decline":
        res = decline()
    else:
        ap.print_help(sys.stderr)
        return 2
    print(json.dumps(res))  # ASCII: see build_screen.main
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
