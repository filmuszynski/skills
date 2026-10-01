# -*- coding: utf-8 -*-
import io
import json
import os
import shutil
import subprocess
import sys

from harness import test, HERE, new_home, use_home, patch

import settings

PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PLUGIN, "hooks"))
import render_plan  # noqa: E402


def plan_file(h, rel="proj/.claude/plans/tidy-plan.md", text="# Tidy\n\n### Task 1: A\n\n- [ ] **Step 1: x**\n"):
    p = os.path.join(h, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with io.open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    return p


def payload(path, cwd=None):
    return {"hook_event_name": "PostToolUse", "tool_name": "Write",
            "tool_input": {"file_path": path, "content": "x"}, "cwd": cwd or os.getcwd()}


def run_main(obj):
    out = io.StringIO()
    raw = obj if isinstance(obj, bytes) else json.dumps(obj).encode("utf-8")
    saved = sys.stdout
    sys.stdout = out
    try:
        code = render_plan.main(io.BytesIO(raw))
    finally:
        sys.stdout = saved
    return code, out.getvalue()


def no_pages(h):
    pd = os.path.join(h, "pages")
    return not os.path.isdir(pd) or os.listdir(pd) == []


@test
def test_plan_path_matches_project_and_home_plan_folders():
    h = new_home()
    a = plan_file(h, "proj/.claude/plans/one.md")
    b = plan_file(h, "home/.claude/plans/saved/two.md")
    assert render_plan.plan_path(a) == os.path.abspath(a)
    assert render_plan.plan_path(b) == os.path.abspath(b)
    assert render_plan.plan_path(a.replace(os.sep, "/")) == os.path.abspath(a)


@test
def test_plan_path_skips_archive_and_other_files():
    h = new_home()
    for rel in ("proj/.claude/plans/archive/old.md", "proj/.claude/plans/Archive/x/old.md",
                "proj/.claude/commands/x.md", "proj/notes.md", "proj/.claude/plans/x.txt"):
        assert render_plan.plan_path(plan_file(h, rel)) is None, rel
    assert render_plan.plan_path(os.path.join(h, "proj/.claude/plans/missing.md")) is None
    for junk in (None, "", 42, "   "):
        assert render_plan.plan_path(junk) is None


@test
def test_relative_paths_resolve_against_the_payload_cwd():
    h = new_home()
    p = plan_file(h, "proj/.claude/plans/rel.md")
    assert render_plan.plan_path(".claude/plans/rel.md", cwd=os.path.join(h, "proj")) == os.path.abspath(p)


@test
def test_context_names_both_lines_buttons_and_expiry():
    res = {"ok": True, "url": "http://127.0.0.1:7777/review/p-abc123.html",
           "path": "/x/.review-doc/pages/p-abc123.html", "sections": 3,
           "server": True, "opened": "vscode", "offerExtension": False, "new": True}
    text = render_plan.context_for(res, 48)
    lines = text.split("\n")
    assert lines[1] == res["url"] and lines[2] == res["path"], lines
    assert "opened in VS Code's built-in browser" in lines[0]
    for word in ("BOTH", "Approve, Decline or Request changes", "comment on any passage"):
        assert word in lines[0], word
    assert lines[3] == ("It covers 3 sections. What they paste is the answer; there is no file "
                        "to read. The page is deleted 48 hours after its last build."), lines[3]
    assert len(lines) == 4 and "—" not in text
    one = render_plan.context_for(dict(res, sections=1, opened=False), 96)
    assert "It covers 1 section." in one and "opened" not in one.split("\n")[0]


@test
def test_context_adds_server_and_extension_lines_when_needed():
    res = {"ok": True, "url": "file:///x/p.html", "path": "/x/p.html", "sections": 2,
           "server": False, "serverNote": "all ports 7777 to 7787 are taken",
           "opened": "browser", "offerExtension": True, "new": True}
    lines = render_plan.context_for(res, 96, python="/usr/bin/python3").split("\n")
    assert len(lines) == 6, lines
    assert "all ports 7777 to 7787 are taken" in lines[4] and "/review-doc:settings" in lines[4]
    ext = os.path.join(PLUGIN, "presenter", "extension.py")
    assert '"/usr/bin/python3" "%s" install' % ext in lines[5], lines[5]
    assert '"/usr/bin/python3" "%s" decline' % ext in lines[5]
    assert "once" in lines[5].lower()


@test
def test_plan_kind_off_is_silent():
    h = use_home(new_home())
    settings.set_value("plan", "off", h)
    code, out = run_main(payload(plan_file(h)))
    assert (code, out) == (0, ""), out
    assert no_pages(h)


@test
def test_a_plan_renders_and_the_hook_speaks_json():
    h = use_home(new_home())
    code, out = run_main(payload(plan_file(h)))
    assert code == 0
    ctx = json.loads(out)["hookSpecificOutput"]
    assert ctx["hookEventName"] == "PostToolUse"
    lines = ctx["additionalContext"].split("\n")
    assert lines[1].startswith("file://") and lines[2].endswith(".html"), lines
    assert os.path.isfile(lines[2])


@test
def test_plan_outside_the_code_page_renders():
    h = use_home(new_home())
    p = plan_file(h, "proj/.claude/plans/plan-łódź.md",
                  "# Plan für Łódź\n\n### Task 1: A\n\n- [ ] **Step 1: x**\n")
    code, out = run_main(payload(p))
    assert code == 0
    text = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert text.startswith("A review page for this plan was generated automatically"), text


@test
def test_renderer_failure_is_reported_and_garbage_is_ignored():
    h = use_home(new_home())
    p = plan_file(h)
    with patch(render_plan, "render", lambda path: (1, '{"ok": false, "error": "disk full"}', "")):
        code, out = run_main(payload(p))
    text = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert code == 0 and text.startswith("The plan review page could not be generated (exit 1).")
    assert "disk full" in text and "unaffected" in text
    with patch(render_plan, "render", lambda path: (3, '{"ok": false, "reason": "disabled", "setting": "plan"}', "")):
        assert run_main(payload(p)) == (0, "")

    def boom(path):
        raise RuntimeError("renderer exploded")
    with patch(render_plan, "render", boom):
        assert run_main(payload(p)) == (0, "")
    for raw in (b"", b"not json", b"[]", b'{"tool_input": "x"}', b"\xff\xfe"):
        assert run_main(raw) == (0, ""), raw


def git_bash():
    if os.name != "nt":
        return shutil.which("bash")
    git = shutil.which("git")
    if git:
        for rel in ("../bin/bash.exe", "../../bin/bash.exe"):
            c = os.path.normpath(os.path.join(os.path.dirname(git), rel))
            if os.path.isfile(c):
                return c
    return None


@test
def test_hooks_json_command_runs_through_bash():
    with io.open(os.path.join(PLUGIN, "hooks", "hooks.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    [entry] = cfg["hooks"]["PostToolUse"]
    assert entry["matcher"] == "Write|Edit"
    [hook] = entry["hooks"]
    assert hook["type"] == "command"
    assert hook["command"] == ('python3 "${CLAUDE_PLUGIN_ROOT}/hooks/render_plan.py" 2>/dev/null'
                               ' || python "${CLAUDE_PLUGIN_ROOT}/hooks/render_plan.py"')
    bash = git_bash()
    assert bash, "bash is needed to run the hook command as Claude Code does"
    h = use_home(new_home())
    raw = json.dumps(payload(plan_file(h))).encode("utf-8")
    r = subprocess.run([bash, "-c", hook["command"]], input=raw, capture_output=True, timeout=60,
                       env=dict(os.environ, CLAUDE_PLUGIN_ROOT=PLUGIN))
    assert r.returncode == 0, r.stderr
    ctx = json.loads(r.stdout.decode("utf-8"))["hookSpecificOutput"]["additionalContext"]
    assert "It covers 1 section." in ctx, ctx


@test
def test_render_returns_when_the_renderer_exits_even_if_a_child_keeps_its_output():
    """On Linux a browser started by xdg-open inherits the renderer's stdout. The hook
    must wait for the renderer, not for every process holding its output."""
    import time
    h = new_home()
    fake = os.path.join(h, "fake_build.py")
    with io.open(fake, "w", encoding="utf-8") as fh:
        fh.write("import subprocess, sys\n"
                 "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(15)'],"
                 " stdout=sys.stdout, stderr=sys.stderr)\n"
                 "print('{\"ok\": true}')\n")
    with patch(render_plan, "BUILD_SCREEN", fake):
        start = time.time()
        code, out, err = render_plan.render(os.path.join(h, "x.md"))
        took = time.time() - start
    assert took < 8, "render() waited %.1f s for a grandchild" % took
    assert (code, out) == (0, '{"ok": true}'), (code, out, err)


@test
def test_context_for_a_rebuilt_plan_is_short():
    res = {"ok": True, "new": False, "url": "http://127.0.0.1:7777/review/p.html",
           "path": "/x/p.html", "sections": 3, "server": True, "opened": False,
           "offerExtension": False}
    lines = render_plan.context_for(res, 96).split("\n")
    assert len(lines) == 3, lines
    assert lines[1:] == [res["url"], res["path"]]
    assert "rebuilt" in lines[0] and "not seen" in lines[0], lines[0]
    new = dict(res, new=True)
    assert len(render_plan.context_for(new, 96).split("\n")) == 4
