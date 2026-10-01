# -*- coding: utf-8 -*-
"""Open a freshly rendered page: in VS Code's built-in browser inside a VS Code
terminal with the opener extension installed, in the system browser everywhere else.
Never fails the render, and never keeps the caller's output open: the link is printed
either way."""
import glob
import os
import shutil
import subprocess
import sys
import webbrowser
from urllib.parse import quote

EXTENSION = "filmuszynski.review-doc-opener"
OPENER = "vscode://%s/open?url=" % EXTENSION


def extension_installed():
    """A folder check, because `code --list-extensions` takes seconds."""
    custom = os.environ.get("VSCODE_EXTENSIONS")
    home = os.path.expanduser("~")
    roots = [custom] if custom else [os.path.join(home, ".vscode", "extensions"),
                                     os.path.join(home, ".vscode-insiders", "extensions")]
    return any(glob.glob(os.path.join(r, EXTENSION + "-*")) for r in roots)


def open_in_vscode(url):
    """As a Ctrl+click would. `code --open-url` takes nothing but vscode:// links, so
    this goes through the extension, which only accepts http(s) review links."""
    if os.environ.get("TERM_PROGRAM") != "vscode" or not url.startswith("http"):
        return False
    code = shutil.which("code")
    if not code or not extension_installed():
        return False
    try:
        subprocess.Popen([code, "--open-url", OPENER + quote(url, safe="")],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return True
    except Exception:  # noqa: BLE001
        return False


def browser_tool(platform=None):
    """The command that opens a URL in the default browser, or None to use webbrowser."""
    platform = platform or sys.platform
    if platform == "darwin":
        return "open"
    if platform.startswith("win"):
        return None
    return "xdg-open"


def system_open(url):
    """Open url in the system browser without handing it our stdout.

    webbrowser starts xdg-open with this process's stdout, and the browser it starts
    keeps it. Anyone reading our output through a pipe (the Bash tool, the plan hook)
    would then wait until the browser closes. A detached child with its own session
    and no inherited streams cannot do that.
    """
    tool = browser_tool()
    path = shutil.which(tool) if tool else None
    if not path:
        return webbrowser.open(url)
    subprocess.Popen([path, url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return True


def open_page(url):
    if open_in_vscode(url):
        return "vscode"
    try:
        return "browser" if system_open(url) else False
    except Exception:  # noqa: BLE001
        return False
