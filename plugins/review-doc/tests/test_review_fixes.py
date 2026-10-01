# -*- coding: utf-8 -*-
"""Fixes from the Phase 2 final review."""
import contextlib
import io
import json
import os
import threading

from harness import test, new_home, use_home, env, patch
from serverkit import serving, review_server

import build_screen
import launch
import settings
import shell


def held_open(path, seconds=0.4):
    """Keep path open for reading for a while, as the server does while serving it.
    On Windows that blocks os.replace onto path until the reader closes."""
    fh = open(path, "rb")
    threading.Timer(seconds, fh.close).start()


@test
def test_page_write_waits_for_a_reader():
    h = new_home()
    target = os.path.join(h, "page.html")
    shell.write(target, "old")
    held_open(target)
    shell.write(target, "new")
    assert io.open(target, encoding="utf-8").read() == "new"


@test
def test_server_json_write_waits_for_a_reader():
    h = new_home()
    target = os.path.join(h, "server.json")
    review_server._write_json(target, {"port": 1})
    held_open(target)
    review_server._write_json(target, {"port": 2})
    assert json.load(io.open(target, encoding="utf-8")) == {"port": 2}


@test
def test_settings_save_waits_for_a_slow_reader():
    h = new_home()
    settings.set_value("stale-hours", "10", h)
    held_open(os.path.join(h, "config.json"))
    assert settings.set_value("stale-hours", "20", h)["stale_hours"] == 20


@test
def test_main_reports_os_errors_as_json():
    h = use_home(new_home())
    s = os.path.join(h, "a.md")
    io.open(s, "w", encoding="utf-8").write("# A\n")

    def denied(path, html):
        raise PermissionError(13, "Access is denied", path)
    out = io.StringIO()
    with patch(shell, "write", denied), contextlib.redirect_stdout(out):
        code = build_screen.main(["doc", s])
    res = json.loads(out.getvalue())
    assert code == 1 and res["ok"] is False and "denied" in res["error"], res


@test
def test_server_main_logs_a_crash():
    h = use_home(new_home())

    def broken(self):
        raise OSError("disk on fire")
    with patch(review_server.ReviewServer, "start", broken):
        code = review_server.main()
    assert code == 1
    log = io.open(os.path.join(h, "server.log"), encoding="utf-8").read()
    assert "disk on fire" in log, log


@test
def test_newer_server_is_used_not_replaced():
    h = use_home(new_home())

    def boom(home=None):
        raise AssertionError("spawned over a newer server")
    with serving(h, version="99.0.0") as newer:
        with env(REVIEW_DOC_NO_SERVER=None), patch(launch, "spawn", boom):
            port, why = launch.ensure_server(h)
        assert port == newer.port, why
        assert not newer.stopping.is_set()


@test
def test_version_order():
    k = launch.version_key
    assert k("0.1.0-dev") < k("0.1.0") < k("0.1.1") < k("1.0.0") < k("1.10.0")
    assert k("0.0.1-old") < k("0.1.0-dev")
    assert k("garbage") < k("0.0.1")


@test
def test_paste_back_tells_claude_to_render_again_with_review_doc():
    """The answer a page copies must name a step any Claude can take, not a private path."""
    import layout_doc
    import layout_plan
    plan = layout_plan.build("# P\n\n### Task 1: A\n\n- [ ] **Step 1: x**\n", source="/x/p.md")
    doc = layout_doc.build("# T\n\n## A\n\nx\n", source="/x/t.md")
    for built in (plan, doc):
        footer = built["prompt_spec"]["footer"]
        assert "build_screen.py" not in footer, footer
        assert "render its review page again with review-doc" in footer, footer
        assert "/x/" in footer, "the source file is still named"


@test
def test_plan_header_fields_keep_their_wrapped_lines():
    import layout_plan
    raw = ("# P\n\n> **For agentic workers:** use a skill.\n\n"
           "**Goal:** first line\nsecond line\nthird line.\n\n"
           "**Architecture:** one line only.\n"
           "**Tech Stack:** Python.\n\n### Task 1: A\n\n- [ ] **Step 1: x**\n")
    meta = layout_plan.parse(raw)["meta"]
    assert meta["Goal"] == "first line second line third line.", meta
    assert meta["Architecture"] == "one line only.", meta
    assert meta["Tech Stack"] == "Python.", meta
    assert not any("agentic" in v for v in meta.values()), meta


@test
def test_plan_footer_names_the_marker_the_page_writes():
    """The page writes 'DECLINE the step'; a footer about SKIP leaves Claude guessing."""
    import io as _io
    import layout_plan
    from harness import PRESENTER
    plan = layout_plan.build("# P\n\n### Task 1: A\n\n- [ ] **Step 1: x**\n", source="/x/p.md")
    footer = plan["prompt_spec"]["footer"]
    js = _io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert 'DECLINE the step' in js
    assert "SKIP" not in footer and "DECLINE" in footer, footer
