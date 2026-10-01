# -*- coding: utf-8 -*-
import contextlib
import io
import json
import os
import subprocess

from harness import test, new_home, use_home, env, patch

import build_screen
import opening
import settings


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def run_main(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = build_screen.main(argv)
    return code, json.loads(out.getvalue())


def recorder(answer):
    calls = []

    def fn(*a, **kw):
        calls.append(a)
        return answer
    return calls, fn


@test
def test_new_page_opens_once():
    h = use_home(new_home())
    s = write(os.path.join(h, "src", "a.md"), "# A\n\n## B\n\nx\n")
    calls, fn = recorder("browser")
    with env(REVIEW_DOC_NO_OPEN=None), patch(opening, "open_page", fn):
        assert run_main(["doc", s])[1]["opened"] == "browser"
        write(s, "# A\n\n## B\n\ny\n")
        assert run_main(["doc", s])[1]["opened"] is False
    assert len(calls) == 1


@test
def test_auto_open_off_opens_nothing():
    h = use_home(new_home())
    settings.set_value("auto-open", "off", h)
    s = write(os.path.join(h, "src", "a.md"), "# A\n\n## B\n\nx\n")
    calls, fn = recorder("browser")
    with env(REVIEW_DOC_NO_OPEN=None), patch(opening, "open_page", fn):
        assert run_main(["doc", s])[1]["opened"] is False
    assert calls == []


@test
def test_no_open_flag_and_env():
    h = use_home(new_home())
    calls, fn = recorder("browser")
    with patch(opening, "open_page", fn):
        s1 = write(os.path.join(h, "src", "one.md"), "# A\n")
        assert run_main(["doc", s1])[1]["opened"] is False  # REVIEW_DOC_NO_OPEN from the harness
        with env(REVIEW_DOC_NO_OPEN=None):
            s2 = write(os.path.join(h, "src", "two.md"), "# A\n")
            assert run_main(["doc", s2, "--no-open"])[1]["opened"] is False
    assert calls == []


@test
def test_vscode_needs_terminal_extension_and_http():
    h = new_home()
    ext_root = os.path.join(h, "extensions")
    os.makedirs(ext_root)
    url = "http://localhost:7777/review/x.html"
    popen_calls, popen = recorder(None)
    with env(VSCODE_EXTENSIONS=ext_root, TERM_PROGRAM="vscode"), \
            patch(opening.shutil, "which", lambda name: "code"), \
            patch(subprocess, "Popen", popen):
        assert opening.extension_installed() is False
        assert opening.open_in_vscode(url) is False, "no extension, no VS Code"
        os.makedirs(os.path.join(ext_root, opening.EXTENSION + "-0.1.0"))
        assert opening.extension_installed() is True
        assert opening.open_in_vscode("file:///x.html") is False, "the extension takes http only"
        assert opening.open_in_vscode(url) is True
        with env(TERM_PROGRAM=None):
            assert opening.open_in_vscode(url) is False, "outside a VS Code terminal"
    assert len(popen_calls) == 1
    argv = popen_calls[0][0]
    assert argv[:2] == ["code", "--open-url"] and argv[2].startswith(opening.OPENER)


@test
def test_falls_back_to_system_browser():
    calls, fn = recorder(True)
    with patch(opening, "open_in_vscode", lambda url: False), patch(opening, "system_open", fn):
        assert opening.open_page("file:///tmp/x.html") == "browser"
        assert opening.open_page("http://localhost:7777/review/x.html") == "browser"
    with patch(opening, "open_in_vscode", lambda url: True), patch(opening, "system_open", fn):
        assert opening.open_page("http://localhost:7777/review/x.html") == "vscode"
    with patch(opening, "open_in_vscode", lambda url: False), \
            patch(opening, "system_open", lambda url: False):
        assert opening.open_page("http://localhost:7777/review/x.html") is False

    def boom(url):
        raise OSError("no browser")
    with patch(opening, "open_in_vscode", lambda url: False), patch(opening, "system_open", boom):
        assert opening.open_page("http://localhost:7777/review/x.html") is False
    assert len(calls) == 2


@test
def test_browser_tool_per_platform():
    assert opening.browser_tool("darwin") == "open"
    assert opening.browser_tool("linux") == "xdg-open"
    assert opening.browser_tool("freebsd13") == "xdg-open"
    assert opening.browser_tool("win32") is None


@test
def test_system_open_detaches_the_tool():
    calls = []

    def popen(argv, **kw):
        calls.append((argv, kw))
    with patch(opening, "browser_tool", lambda platform=None: "xdg-open"), \
            patch(opening.shutil, "which", lambda name: "/usr/bin/" + name), \
            patch(subprocess, "Popen", popen):
        assert opening.system_open("http://127.0.0.1:7777/review/a.html") is True
    (argv, kw), = calls
    assert argv == ["/usr/bin/xdg-open", "http://127.0.0.1:7777/review/a.html"]
    for stream in ("stdin", "stdout", "stderr"):
        assert kw.get(stream) is subprocess.DEVNULL, stream
    assert kw.get("start_new_session") is True


@test
def test_system_open_falls_back_to_webbrowser():
    calls, fn = recorder(True)
    with patch(opening, "browser_tool", lambda platform=None: None), \
            patch(opening.webbrowser, "open", fn):
        assert opening.system_open("file:///tmp/x.html") is True
    with patch(opening, "browser_tool", lambda platform=None: "xdg-open"), \
            patch(opening.shutil, "which", lambda name: None), \
            patch(opening.webbrowser, "open", fn):
        assert opening.system_open("file:///tmp/x.html") is True
    assert len(calls) == 2


def fake_browser_dir(h, marker):
    """A folder holding fake `open` and `xdg-open` that note they ran, then keep
    running for 15 s with whatever stdout they were given, as a browser would."""
    d = os.path.join(h, "bin")
    os.makedirs(d)
    for name in ("open", "xdg-open"):
        p = os.path.join(d, name)
        with io.open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("#!/bin/sh\necho ran > '%s'\nsleep 15\n" % marker)
        os.chmod(p, 0o755)
    return d


@test
def test_posix_open_does_not_hold_the_callers_output():
    """Review Focus 1. On Linux the browser xdg-open starts inherits our stdout; a
    caller reading it through a pipe (the Bash tool, the plan hook) would wait for the
    browser to close."""
    import sys
    import time
    if os.name == "nt":
        print("  (skip) POSIX only; runs on macOS and Linux in CI")
        return
    h = new_home()
    marker = os.path.join(h, "ran")
    bindir = fake_browser_dir(h, marker)
    presenter = os.path.dirname(opening.__file__)
    code = ("import sys; sys.path.insert(0, %r); import opening; "
            "print(opening.open_page('http://127.0.0.1:7777/review/a.html'))" % presenter)
    child_env = dict(os.environ, PATH=bindir + os.pathsep + os.environ.get("PATH", ""),
                     DISPLAY=":0", BROWSER="")
    child_env.pop("TERM_PROGRAM", None)
    start = time.time()
    r = subprocess.run([sys.executable, "-c", code], env=child_env,
                       capture_output=True, text=True, timeout=30)
    took = time.time() - start
    assert took < 8, "the caller waited %.1f s for the browser" % took
    assert r.stdout.strip() == "browser", (r.stdout, r.stderr)
    for _ in range(50):
        if os.path.isfile(marker):
            break
        time.sleep(0.1)
    assert os.path.isfile(marker), "the fake browser never ran"


@test
def test_offer_only_comes_with_a_new_page():
    """M6: editing an existing page must not repeat the extension question."""
    import extension
    h = use_home(new_home())
    s = write(os.path.join(h, "src", "a.md"), "# A\n\n## B\n\nx\n")
    with patch(extension, "should_offer", lambda home=None: True):
        assert run_main(["doc", s])[1]["offerExtension"] is True
        write(s, "# A\n\n## B\n\ny\n")
        again = run_main(["doc", s])[1]
    assert again["new"] is False and again["offerExtension"] is False, again
