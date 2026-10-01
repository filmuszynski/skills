# -*- coding: utf-8 -*-
import contextlib
import io
import json
import os
import subprocess

from harness import test, new_home, use_home, env, patch

import build_screen
import extension
import opening
import paths
import settings


def machine(h, terminal=True, code=True, installed=False):
    """A VS Code terminal with `code` on PATH and an empty extensions folder, by default."""
    ext_root = os.path.join(h, "extensions")
    os.makedirs(ext_root, exist_ok=True)
    if installed:
        os.makedirs(os.path.join(ext_root, opening.EXTENSION + "-0.1.0"), exist_ok=True)
    stack = contextlib.ExitStack()
    stack.enter_context(env(VSCODE_EXTENSIONS=ext_root, TERM_PROGRAM="vscode" if terminal else None))
    stack.enter_context(patch(extension.shutil, "which", lambda name: "code" if code and name == "code" else None))
    return stack


def ran(returncode=0, stderr=""):
    calls = []

    def fake(argv, **kw):
        calls.append(list(argv))
        assert os.path.isfile(argv[2]), "the .vsix exists while code installs it"
        return subprocess.CompletedProcess(argv, returncode, "", stderr)
    return calls, fake


def write_bytes(path, data):
    with io.open(path, "wb") as fh:
        fh.write(data)
    return path


@test
def test_offer_needs_terminal_code_no_extension_and_no_answer():
    h = use_home(new_home())
    with machine(h):
        assert extension.should_offer() is True
    with machine(h, terminal=False):
        assert extension.should_offer() is False
    with machine(h, code=False):
        assert extension.should_offer() is False
    with machine(h, installed=True):
        assert extension.should_offer() is False
    with machine(h):
        assert extension.decline()["ok"] is True
        assert extension.should_offer() is False
        assert settings.load()["vscode_asked"] is True


@test
def test_install_from_a_local_vsix():
    h = use_home(new_home())
    vsix = write_bytes(os.path.join(h, "local.vsix"), b"PK")
    calls, fake = ran()
    with machine(h), patch(extension.subprocess, "run", fake):
        res = extension.install(vsix=vsix)
    assert res["ok"] is True, res
    assert calls == [["code", "--install-extension", vsix, "--force"]], calls
    assert settings.load()["vscode_asked"] is True
    assert os.path.isfile(vsix), "a file the user passed is never deleted"


@test
def test_install_failure_is_reported_and_still_counts_as_asked():
    h = use_home(new_home())
    vsix = write_bytes(os.path.join(h, "local.vsix"), b"PK")
    calls, fake = ran(1, "Failed Installing Extensions: boom")
    with machine(h), patch(extension.subprocess, "run", fake):
        res = extension.install(vsix=vsix)
    assert res["ok"] is False and "boom" in res["message"], res
    assert settings.load()["vscode_asked"] is True
    with machine(h):
        missing = extension.install(vsix=os.path.join(h, "nope.vsix"))
    assert missing["ok"] is False and "nope.vsix" in missing["message"]


@test
def test_install_without_code_on_path_says_how():
    h = use_home(new_home())
    with machine(h, code=False):
        res = extension.install()
    assert res["ok"] is False and "Shell Command: Install 'code' command in PATH" in res["message"], res
    assert settings.load()["vscode_asked"] is True


@test
def test_a_development_version_has_no_release_to_download():
    h = use_home(new_home())
    with machine(h), patch(paths, "version", lambda: "0.1.0-dev"):
        assert extension.release_url() is None
        res = extension.install()
    assert res["ok"] is False and "--vsix" in res["message"], res


@test
def test_release_url_is_pinned_to_the_plugin_version():
    assert extension.release_url("1.2.3") == (
        "https://github.com/filmuszynski/skills/releases/download/v1.2.3/review-doc-opener.vsix")


@test
def test_install_downloads_the_release_and_removes_the_download():
    h = use_home(new_home())
    seen = []

    def fake_urlopen(url, timeout=None):
        seen.append(url)
        return io.BytesIO(b"PK-release")
    calls, fake = ran()
    with machine(h), patch(paths, "version", lambda: "1.2.3"), \
            patch(extension.urllib.request, "urlopen", fake_urlopen), \
            patch(extension.subprocess, "run", fake):
        res = extension.install()
    assert res["ok"] is True, res
    assert seen == [extension.release_url("1.2.3")]
    assert not os.path.exists(calls[0][2]), "the downloaded .vsix is removed afterwards"


@test
def test_download_failure_names_the_url_and_runs_nothing():
    h = use_home(new_home())

    def broken(url, timeout=None):
        raise OSError("HTTP Error 404: Not Found")
    calls, fake = ran()
    with machine(h), patch(paths, "version", lambda: "1.2.3"), \
            patch(extension.urllib.request, "urlopen", broken), \
            patch(extension.subprocess, "run", fake):
        res = extension.install()
    assert res["ok"] is False and extension.release_url("1.2.3") in res["message"], res
    assert calls == []


@test
def test_renderer_result_says_whether_to_offer():
    h = use_home(new_home())
    src = os.path.join(h, "a.md")
    with io.open(src, "w", encoding="utf-8") as fh:
        fh.write("# A\n\n## B\n\nx\n")

    def run(argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            build_screen.main(argv)
        return json.loads(out.getvalue())
    with machine(h):
        assert run(["doc", src])["offerExtension"] is True
        extension.decline()
        assert run(["doc", src])["offerExtension"] is False


@test
def test_cli_prints_one_json_line():
    h = use_home(new_home())
    with machine(h):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert extension.main(["status"]) == 0
        got = json.loads(out.getvalue())
        assert got["offer"] is True and set(got) == {"vscodeTerminal", "code", "installed", "asked", "offer"}
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            assert extension.main(["decline"]) == 0
            assert extension.main(["bogus"]) == 2
