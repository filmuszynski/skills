# -*- coding: utf-8 -*-
"""PostToolUse hook (Write|Edit): turns a plan Markdown file into its review page.

Why a hook: plan mode lets Claude write nothing but the plan itself, so Claude
cannot render the page while planning. The harness runs hooks regardless.

It renders `.md` files under any `.claude/plans/` folder, the project's or
~/.claude/plans/ (Claude Code's default), except inside an `archive/` folder.

Fails soft in every branch and always exits 0: a broken renderer must never cost
the user their plan.
"""
from __future__ import print_function

import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PRESENTER = os.path.join(ROOT, "presenter")
BUILD_SCREEN = os.path.join(PRESENTER, "build_screen.py")
EXTENSION = os.path.join(PRESENTER, "extension.py")
sys.path.insert(0, PRESENTER)

PLAN_RE = re.compile(r"/\.claude/plans/(.+\.md)$", re.IGNORECASE)
LIMIT = 600


def plan_path(file_path, cwd=None):
    """The absolute path of a plan this hook renders, or None."""
    if not isinstance(file_path, str) or not file_path.strip():
        return None
    p = file_path if os.path.isabs(file_path) else os.path.join(cwd or os.getcwd(), file_path)
    p = os.path.abspath(p)
    m = PLAN_RE.search(p.replace("\\", "/"))
    if not m:
        return None
    if "archive" in [s.lower() for s in m.group(1).split("/")[:-1]]:
        return None
    return p if os.path.isfile(p) else None


def context_for(result, stale_hours, python=None):
    python = python or sys.executable
    if result.get("new") is False:
        return "\n".join([
            "The review page for this plan was rebuilt with the change. If the user has "
            "not seen it yet, give them both lines, each alone on its own line:",
            result["url"],
            result["path"],
        ])
    opened ={"vscode": " and opened in VS Code's built-in browser",
              "browser": " and opened in the browser"}.get(result.get("opened"), "")
    n = int(result.get("sections") or 0)
    lines = [
        "A review page for this plan was generated automatically%s. Give the user BOTH of "
        "these, each alone on its own line, and tell them they can comment on any passage, "
        "rewrite text in place, and approve or decline individual sections and steps, then "
        "finish with Approve, Decline or Request changes, which copies the answer so they "
        "can paste it back:" % opened,
        result["url"],
        result["path"],
        "It covers %d section%s. What they paste is the answer; there is no file to read. "
        "The page is deleted %d hours after its last build." % (n, "" if n == 1 else "s", stale_hours),
    ]
    if not result.get("server"):
        lines.append("The review server is not running (%s), so the link opens the page as a "
                     "file. Comments and the answer still work; settings need "
                     "/review-doc:settings." % (result.get("serverNote") or "no reason given"))
    if result.get("offerExtension"):
        cmd = '"%s" "%s"' % (python, EXTENSION)
        lines.append("Once the plan is settled, ask the user once whether review pages should "
                     "open inside VS Code's built-in browser, through a small extension from "
                     "the plugin's GitHub release. On yes run: %s install. On no run: %s "
                     "decline. Either answer is recorded, so do not ask again." % (cmd, cmd))
    return "\n".join(lines)


def failure(code, said):
    return ("The plan review page could not be generated (exit %s). The plan Markdown is "
            "unaffected. Tell the user the link is unavailable this time; do not retry "
            "silently. Renderer said: %s" % (code, (said or "")[:LIMIT]))


def render(path):
    """Run the renderer; (exit code, stdout, stderr), all text.

    Output goes to temporary files, not pipes. A pipe stays open as long as any
    process holds it, and a browser that xdg-open starts on Linux inherits the
    renderer's stdout, so reading a pipe would wait for the browser to close.
    """
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        r = subprocess.run([sys.executable, BUILD_SCREEN, "plan", path], env=env,
                           stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=45,
                           creationflags=flags)
        out.seek(0)
        err.seek(0)
        return (r.returncode, out.read().decode("utf-8", "replace").strip(),
                err.read().decode("utf-8", "replace").strip())


def handle(payload):
    """The additionalContext text for one hook payload, or None to stay silent."""
    if not isinstance(payload, dict):
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    path = plan_path(tool_input.get("file_path"), payload.get("cwd"))
    if not path:
        return None
    import settings
    cfg = settings.load()
    if not cfg["kinds"]["plan"]:
        return None
    try:
        code, out, err = render(path)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return failure("-", str(exc))
    try:
        result = json.loads(out.splitlines()[-1]) if out else None
    except ValueError:
        result = None
    if code == 3 and isinstance(result, dict) and result.get("reason") == "disabled":
        return None
    if code != 0 or not isinstance(result, dict) or not result.get("ok"):
        return failure(code, out or err)
    return context_for(result, cfg["stale_hours"])


def emit(text):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                             "additionalContext": text}}))


def main(stream=None):
    try:
        raw = (stream or sys.stdin.buffer).read().decode("utf-8", "replace")
        if raw.strip():
            text = handle(json.loads(raw))
            if text:
                emit(text)
    except Exception:  # noqa: BLE001  (fail soft: never cost the user their plan)
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
