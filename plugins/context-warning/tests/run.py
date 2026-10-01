# -*- coding: utf-8 -*-
"""Tests for the context-warning plugin. Standard library only, no pytest.

    python plugins/context-warning/tests/run.py
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(PLUGIN))
HOOK = os.path.join(PLUGIN, "hooks", "context_warning.py")

TESTS = []
BOXES = []


def test(fn):
    TESTS.append(fn)
    return fn


class Box:
    """One scratch folder per test: the transcript and the hook's state dir (via TMP)."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="cw-test-")
        self.transcript = os.path.join(self.dir, "t.jsonl")
        BOXES.append(self.dir)

    def model(self, model_id="claude-opus-5-5[1m]", name="Opus 5.5 (1M context)"):
        self.add({"type": "attachment", "attachment": {"type": "model", "identity": {
            "modelId": model_id, "marketingName": name}}})

    def plain_model(self):
        self.model("claude-sonnet-5-5", "Sonnet 5.5")

    def usage(self, tokens, **flags):
        entry = {"type": "assistant", "message": {"usage": {
            "input_tokens": tokens, "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0}}}
        entry.update(flags)
        self.add(entry)

    def add(self, entry):
        self.raw(json.dumps(entry, separators=(",", ":")))

    def raw(self, line):
        with io.open(self.transcript, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def state_dir(self):
        return os.path.join(self.dir, "claude-context-warn")

    def run(self, event="UserPromptSubmit", session="s1", stdin=None, env=None):
        e = dict(os.environ)
        e.pop("CLAUDE_CONTEXT_WINDOW", None)
        for k in ("TMPDIR", "TEMP", "TMP"):
            e[k] = self.dir
        e.update(env or {})
        if stdin is None:
            stdin = json.dumps({"transcript_path": self.transcript, "session_id": session,
                                "hook_event_name": event})
        p = subprocess.run([sys.executable, HOOK], input=stdin.encode("utf-8"),
                           capture_output=True, env=e, timeout=30)
        assert p.returncode == 0, (p.returncode, p.stderr)
        out = p.stdout.decode("ascii")  # ASCII-only by design; raises otherwise
        return json.loads(out) if out.strip() else None


def line(out):
    return out["systemMessage"] if out else None


def has_note(out):
    return bool(out) and "hookSpecificOutput" in out


# ---------------------------------------------------------------- behaviour


@test
def test_below_30_is_silent():
    b = Box()
    b.model()
    b.usage(250000)
    assert b.run("UserPromptSubmit") is None
    assert b.run("PostToolUse") is None


@test
def test_30_repeats_on_every_prompt_with_one_note():
    b = Box()
    b.model()
    b.usage(350000)
    first = b.run()
    assert "\U0001F7E1 Context at 35% (350k of 1M tokens): fine for now" in line(first)
    assert line(first).startswith("\n\x1b[92m") and line(first).endswith("\x1b[0m")
    assert first["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "keep an eye on it" in first["hookSpecificOutput"]["additionalContext"]
    second = b.run()
    assert "Context at 35%" in line(second) and not has_note(second)


@test
def test_tool_calls_stay_quiet_after_the_level_fired():
    b = Box()
    b.model()
    b.usage(350000)
    b.run()
    assert b.run("PostToolUse") is None


@test
def test_first_crossing_on_a_tool_call_shows_once():
    b = Box()
    b.model()
    b.usage(450000)
    out = b.run("PostToolUse")
    assert "\U0001F7E0 Context at 45%" in line(out)
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert b.run("PostToolUse") is None
    again = b.run("UserPromptSubmit")
    assert "\U0001F7E0" in line(again) and not has_note(again)


@test
def test_red_note_once_then_line_only():
    b = Box()
    b.model()
    b.usage(550000)
    first = b.run()
    assert "\U0001F534 Context at 55%" in line(first) and has_note(first)
    assert line(first).startswith("\n\x1b[91m")
    assert "/compact" in first["hookSpecificOutput"]["additionalContext"]
    for _ in range(2):
        out = b.run()
        assert "\U0001F534" in line(out) and not has_note(out)


@test
def test_jump_shows_only_the_highest_level():
    b = Box()
    b.model()
    b.usage(250000)
    assert b.run() is None
    b.usage(450000)
    out = b.run()
    assert "\U0001F7E0" in line(out) and "\U0001F7E1" not in line(out) and has_note(out)
    nxt = b.run()
    assert "\U0001F7E0" in line(nxt) and not has_note(nxt)


@test
def test_compact_lets_levels_fire_again():
    b = Box()
    b.model()
    b.usage(550000)
    b.run()
    b.usage(200000)
    assert b.run() is None
    b.usage(350000)
    out = b.run()
    assert "\U0001F7E1" in line(out) and has_note(out)


# ---------------------------------------------------------------- window


@test
def test_plain_model_means_200k():
    b = Box()
    b.plain_model()
    b.usage(70000)
    assert "Context at 35% (70k of 200k tokens)" in line(b.run())


@test
def test_env_override_wins():
    b = Box()
    b.model()
    b.usage(35000)
    out = b.run(env={"CLAUDE_CONTEXT_WINDOW": "100000"})
    assert "(35k of 100k tokens)" in line(out)


@test
def test_last_model_attachment_wins():
    b = Box()
    b.model()
    b.plain_model()
    b.usage(70000)
    assert "of 200k" in line(b.run())


@test
def test_model_switch_overrides_cached_window():
    b = Box()
    b.model()
    b.usage(350000)
    assert "of 1M" in line(b.run())
    b.plain_model()
    b.usage(70000)
    assert "of 200k" in line(b.run())


@test
def test_usage_above_window_assumes_1m():
    b = Box()
    b.plain_model()
    b.usage(300000)
    assert "(300k of 1M tokens)" in line(b.run())


@test
def test_no_model_attachment_defaults_to_200k():
    b = Box()
    b.usage(70000)
    assert "of 200k" in line(b.run())


# ---------------------------------------------------------------- robustness


@test
def test_ignores_sidechain_error_and_garbage_lines():
    b = Box()
    b.raw('{"half a line from the tail cut "usage"')
    b.model()
    b.usage(350000)
    b.usage(900000, isSidechain=True)
    b.usage(900000, isApiErrorMessage=True)
    b.raw('not json but has "usage" in it')
    assert "Context at 35%" in line(b.run())


@test
def test_broken_input_is_silent():
    b = Box()
    assert b.run(stdin="not json") is None
    assert b.run(stdin="") is None
    assert b.run(stdin=json.dumps({"transcript_path": os.path.join(b.dir, "missing.jsonl")})) is None
    b.model()
    assert b.run() is None  # transcript without usage


@test
def test_session_id_cannot_escape_state_dir():
    b = Box()
    b.model()
    b.usage(350000)
    b.run(session="../../escape")
    b.run(session="")
    assert not os.path.exists(os.path.join(b.dir, "escape.json"))
    assert not os.path.exists(os.path.join(os.path.dirname(b.dir), "escape.json"))
    names = os.listdir(b.state_dir())
    assert len(names) == 2 and all(n.endswith(".json") for n in names), names


@test
def test_old_list_state_is_read():
    b = Box()
    os.makedirs(b.state_dir())
    with io.open(os.path.join(b.state_dir(), "s1.json"), "w", encoding="utf-8") as fh:
        fh.write("[30]")
    b.model()
    b.usage(350000)
    out = b.run()
    assert "Context at 35%" in line(out) and not has_note(out)


@test
def test_corrupt_state_is_ignored():
    b = Box()
    os.makedirs(b.state_dir())
    with io.open(os.path.join(b.state_dir(), "s1.json"), "w", encoding="utf-8") as fh:
        fh.write("{nope")
    b.model()
    b.usage(350000)
    assert has_note(b.run())


@test
def test_quiet_right_after_compact_until_fresh_usage():
    b = Box()
    b.model()
    b.usage(550000)
    b.run()
    b.add({"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted"})
    b.add({"type": "user", "isCompactSummary": True, "message": {"role": "user", "content": "summary"}})
    assert b.run() is None, "pre-compact usage must not be shown as current"
    b.usage(350000)
    out = b.run()
    assert "\U0001F7E1 Context at 35%" in line(out) and has_note(out)


@test
def test_bad_usage_value_skips_that_entry():
    b = Box()
    b.model()
    b.usage(350000)
    b.add({"type": "assistant", "message": {"usage": {"input_tokens": "lots"}}})
    assert "Context at 35%" in line(b.run())


@test
def test_model_found_outside_a_large_tail():
    b = Box()
    b.model()
    filler = json.dumps({"type": "user", "message": {"content": "x" * 1000}})
    with io.open(b.transcript, "a", encoding="utf-8") as fh:
        fh.write((filler + "\n") * 2600)  # about 2.6 MB, past the 2 MB tail
    b.usage(350000)
    assert "of 1M" in line(b.run())
    names = os.listdir(b.state_dir())
    with io.open(os.path.join(b.state_dir(), names[0]), encoding="utf-8") as fh:
        assert json.load(fh)["window"] == 1000000, "window cached after one full scan"


@test
def test_no_temp_file_left_behind():
    b = Box()
    b.model()
    b.usage(350000)
    b.run()
    assert os.listdir(b.state_dir()) == ["s1.json"], os.listdir(b.state_dir())


@test
def test_output_is_ascii_only():
    b = Box()
    b.model()
    b.usage(550000)
    out = b.run()  # run() already decodes stdout as ASCII
    assert "\U0001F534" in line(out)


# ---------------------------------------------------------------- packaging


def read_json(*parts):
    with io.open(os.path.join(*parts), encoding="utf-8") as fh:
        return json.load(fh)


def read_text(*parts):
    with io.open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


@test
def test_plugin_manifest():
    m = read_json(PLUGIN, ".claude-plugin", "plugin.json")
    assert m["name"] == "context-warning" and m["license"] == "MIT"
    assert re.fullmatch(r"\d+\.\d+\.\d+", m["version"]), m["version"]
    assert m["homepage"] == "https://github.com/filmuszynski/skills"


@test
def test_hooks_use_the_launcher_chain_on_both_events():
    h = read_json(PLUGIN, "hooks", "hooks.json")["hooks"]
    want = ('python3 "${CLAUDE_PLUGIN_ROOT}/hooks/context_warning.py" 2>/dev/null'
            ' || python "${CLAUDE_PLUGIN_ROOT}/hooks/context_warning.py"')
    assert set(h) == {"UserPromptSubmit", "PostToolUse"}, set(h)
    assert h["PostToolUse"][0]["matcher"] == "*"
    for event in h:
        cmd = h[event][0]["hooks"][0]
        assert cmd["type"] == "command" and cmd["command"] == want and cmd["timeout"] == 5


@test
def test_marketplace_lists_the_plugin():
    m = read_json(REPO, ".claude-plugin", "marketplace.json")
    entry = [p for p in m["plugins"] if p["name"] == "context-warning"]
    assert entry and entry[0]["source"] == "./plugins/context-warning" and entry[0]["description"]


@test
def test_changelog_has_the_version():
    v = read_json(PLUGIN, ".claude-plugin", "plugin.json")["version"]
    assert "## [%s]" % v in read_text(PLUGIN, "CHANGELOG.md")


@test
def test_ci_runs_these_tests():
    assert "python plugins/context-warning/tests/run.py" in read_text(REPO, ".github", "workflows", "test.yml")


# ---------------------------------------------------------------- runner


def main():
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print("ok   " + fn.__name__)
        except Exception:
            failed += 1
            print("FAIL " + fn.__name__)
            traceback.print_exc()
    for d in BOXES:
        shutil.rmtree(d, ignore_errors=True)
    print("%d passed, %d failed" % (len(TESTS) - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
