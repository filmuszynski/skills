# -*- coding: utf-8 -*-
"""Nothing private may reach the public repo. Sweeps every file a `git add -A` would
commit, not only the plugin: README, workflows, ADRs, screenshots' sources."""
import io
import os
import re
import subprocess

from harness import test, HERE

PLUGIN = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(PLUGIN))
TERMS_FILE = os.path.join(REPO, "sessions", "private-terms.txt")

GENERIC_PATTERNS = [
    # Generic checks only. Names from the author's own setup live in the gitignored
    # sessions/private-terms.txt, so this public file does not spell them out.
    r"[A-Za-z]:[\\/]Users[\\/]",       # absolute Windows home paths
    r"/(?:Users|home)/[a-z]",          # absolute macOS and Linux home paths
    # any email address except GitHub's noreply form and reserved test domains
    # (.example, .invalid, .test), which the opener tests use for hostile links
    r"[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com)(?![A-Za-z0-9-]+\.(?:example|invalid|test)\b)"
    r"[A-Za-z0-9-]+\.[A-Za-z0-9.-]*[A-Za-z]",
    r"\bghp_[A-Za-z0-9]{20,}", r"\bgithub_pat_[A-Za-z0-9_]{20,}",
    r"\bsk-ant-[A-Za-z0-9-]{10,}", r"\bAKIA[0-9A-Z]{16}\b",
]
# Third-party code keeps its authors' addresses; binaries are checked by eye in the sweep.
SKIP_PREFIXES = ("plugins/review-doc/presenter/vendor/",)
BINARY = (".png", ".jpg", ".gif", ".vsix", ".ico")
SELF = "plugins/review-doc/tests/test_privacy.py"


def committable_files():
    """Tracked files plus untracked ones that .gitignore lets through: exactly what a
    `git add -A` would put in the next commit."""
    # Unquoted and NUL-separated: by default git C-quotes a non-ASCII name, which is no
    # path, and the file would be committed without ever being scanned.
    r = subprocess.run(["git", "-c", "core.quotePath=false", "ls-files", "-z",
                        "--cached", "--others", "--exclude-standard"],
                       cwd=REPO, capture_output=True, timeout=30)
    assert r.returncode == 0, r.stderr
    listed = [p for p in r.stdout.decode("utf-8").split("\0") if p]
    # A tracked file deleted in the working tree is still listed; it has nothing to scan.
    deleted = subprocess.run(["git", "-c", "core.quotePath=false", "ls-files", "-z", "--deleted"],
                             cwd=REPO, capture_output=True, timeout=30).stdout.decode("utf-8")
    gone = set(p for p in deleted.split("\0") if p)
    files = [p for p in listed if p not in gone]
    missing = [p for p in files if not os.path.isfile(os.path.join(REPO, p))]
    assert not missing, "listed but not found, so never scanned: %s" % missing
    return files


def swept_files():
    for rel in committable_files():
        if rel == SELF or rel.startswith(SKIP_PREFIXES) or rel.lower().endswith(BINARY):
            continue
        yield rel


def private_terms():
    if not os.path.isfile(TERMS_FILE):
        return []
    with io.open(TERMS_FILE, encoding="utf-8") as fh:
        return [l.strip().lower() for l in fh if l.strip() and not l.startswith("#")]


def scan(text, patterns):
    hits = []
    for pat in patterns:
        for m in re.finditer(pat, text):
            hits.append((text.count("\n", 0, m.start()) + 1, m.group(0)))
    return hits


@test
def test_privacy_sees_every_committable_file():
    files = set(committable_files())
    for must in ("README.md", "CHANGELOG.md", "LICENSE", ".gitignore",
                 "docs/adr/README.md", ".claude-plugin/marketplace.json",
                 "plugins/review-doc/.claude-plugin/plugin.json",
                 "plugins/review-doc/skills/review-doc/SKILL.md"):
        assert must in files, must
    assert not any(p.startswith(("sessions/", ".impeccable/", "docs/specs/", "docs/plans/"))
                   for p in files), sorted(p for p in files if "/" in p)[:5]


@test
def test_privacy_sees_files_with_non_ascii_names():
    """git quotes such names by default; a quoted name is no path, and the file would
    be committed without ever being scanned."""
    probe = os.path.join(REPO, u"privacy-probe-Übersicht.md")
    with io.open(probe, "w", encoding="utf-8") as fh:
        fh.write("probe\n")
    try:
        assert u"privacy-probe-Übersicht.md" in committable_files()
    finally:
        os.remove(probe)


@test
def test_patterns_catch_known_leaks():
    leaks = ["C:\\Users\\someone\\x", "D:/Users/someone/x", "/Users/someone/x",
             "/home/someone/x", "name@example.org", "ghp_" + "a" * 30,
             "sk-ant-" + "b" * 20, "AKIA" + "C" * 16]
    for leak in leaks:
        assert scan(leak, GENERIC_PATTERNS), leak
    clean = ["214140881+filmuszynski@users.noreply.github.com", "npx @vscode/vsce package",
             "~/.review-doc/config.json", "http://127.0.0.1:7777/review/a.html",
             "http://127.0.0.1:7777@evil.example/review/a.html"]
    for ok in clean:
        assert not scan(ok, GENERIC_PATTERNS), ok


@test
def test_no_private_patterns_in_the_repo():
    hits = []
    for rel in swept_files():
        text = io.open(os.path.join(REPO, rel), encoding="utf-8", errors="replace").read()
        hits += ["%s:%d %s" % (rel, line, s) for line, s in scan(text, GENERIC_PATTERNS)]
    assert not hits, "private patterns:\n" + "\n".join(hits)


@test
def test_no_private_terms_in_the_repo():
    terms = private_terms()
    if not terms:
        print("  (skip) no sessions/private-terms.txt on this machine")
        return
    hits = []
    for rel in swept_files():
        low = io.open(os.path.join(REPO, rel), encoding="utf-8", errors="replace").read().lower()
        hits += ["%s: %s" % (rel, t) for t in terms
                 if re.search(r"\b" + re.escape(t) + r"\b", low)]
    assert not hits, "private terms:\n" + "\n".join(hits)
