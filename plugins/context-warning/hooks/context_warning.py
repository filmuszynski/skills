#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Context-window warning for Claude Code (UserPromptSubmit + PostToolUse).

From 30% of the context window, every prompt shows a coloured line for the current
level. Tool calls show it only when a level is first crossed. Claude gets a note once
per level, so the reminder does not pile up in the window. After /compact, levels
above the new usage can fire again. Fails soft: any error exits 0 with no output.

Window size comes from the session's transcript: Claude Code writes a model
attachment at session start and after every /model switch, e.g. modelId
"claude-opus-5-5[1m]", marketingName "Opus 5.5 (1M context)". The last one wins.
Hook input carries no model, and the model id on assistant messages drops the [1m]
suffix. CLAUDE_CONTEXT_WINDOW (tokens) overrides everything.
"""
import json
import os
import re
import sys
import tempfile

LEVELS = [
    (50, "\U0001F534", "\x1b[91m", "compact or hand off now"),
    (40, "\U0001F7E0", "\x1b[33m", "start planning a handoff"),
    (30, "\U0001F7E1", "\x1b[92m", "fine for now, keep an eye on it"),
]
NOTES = {
    50: "The context window is getting full. Suggest /compact or a handoff before continuing large work.",
    40: "Getting close to halfway. Mention it and suggest planning a handoff soon.",
    30: "Still plenty of room, but keep an eye on it.",
}
RESET = "\x1b[0m"
TAIL_BYTES = 2 * 1024 * 1024
MODEL_RE = re.compile(r'"attachment":\{"type":"model","identity":\{"modelId":"([^"]*)",'
                      r'"marketingName":"([^"]*)"')
USAGE_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def read(path, tail_only):
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        n = min(size, TAIL_BYTES) if tail_only else size
        fh.seek(size - n)
        return fh.read(n).decode("utf-8", "replace")


def last_used_tokens(text):
    for raw in reversed(text.split("\n")):
        if '"usage"' not in raw:
            continue
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("isSidechain") or entry.get("isApiErrorMessage"):
            continue
        msg = entry.get("message")
        usage = msg.get("usage") if isinstance(msg, dict) else None
        if not isinstance(usage, dict):
            continue
        total = sum(int(usage.get(k) or 0) for k in USAGE_KEYS)
        if total > 0:
            return total
    return 0


def window_from_model(text):
    """Window of the last model attachment in text, or 0 if there is none."""
    last = None
    for last in MODEL_RE.finditer(text):
        pass
    if last is None:
        return 0
    one_m = "[1m]" in last.group(1).lower() or re.search(r"1M context", last.group(2), re.I)
    return 1000000 if one_m else 200000


def decide(pct, fired, event):
    """Return (level or None, send_note, new_fired) for usage at pct percent."""
    fired = [p for p in fired if p <= pct]  # after /compact, higher levels may fire again
    reached = [lvl for lvl in LEVELS if pct >= lvl[0]]
    if not reached:
        return None, False, fired
    hit = reached[0]
    # Mark every level reached, so a jump from 25% to 45% shows only 40%.
    new_fired = sorted(set(fired) | {lvl[0] for lvl in reached})
    if hit[0] not in fired:
        return hit, True, new_fired
    if event == "UserPromptSubmit":
        return hit, False, new_fired
    return None, False, new_fired


def load_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return {}
    if isinstance(state, list):  # format before 30.09.2026
        state = {"fired": state}
    if not isinstance(state, dict):
        return {}
    fired = state.get("fired")
    state["fired"] = [p for p in fired if isinstance(p, (int, float))] if isinstance(fired, list) else []
    return state


def env_window():
    try:
        return int(os.environ.get("CLAUDE_CONTEXT_WINDOW", ""))
    except ValueError:
        return 0


def main(raw):
    data = json.loads(raw)
    if not isinstance(data, dict):
        return None
    transcript = data.get("transcript_path")
    if not transcript or not os.path.isfile(transcript):
        return None
    event = data.get("hook_event_name") or "UserPromptSubmit"

    state_dir = os.path.join(tempfile.gettempdir(), "claude-context-warn")
    os.makedirs(state_dir, exist_ok=True)
    session = re.sub(r"[^A-Za-z0-9_-]", "_", str(data.get("session_id") or "")) or "unknown"
    state_file = os.path.join(state_dir, session + ".json")
    state = load_state(state_file)

    tail = read(transcript, True)
    used = last_used_tokens(tail)
    if not used:
        return None

    # A /model switch lands in the tail; otherwise reuse the cached window, and
    # scan the whole transcript only once per session.
    win = env_window()
    if win <= 0:
        win = (window_from_model(tail) or state.get("window")
               or window_from_model(read(transcript, False)) or 200000)
        state["window"] = win
    if used > win:  # usage cannot exceed its window; guard a stale guess
        win = 1000000
    pct = used * 100.0 / win

    hit, note, state["fired"] = decide(pct, state.get("fired", []), event)
    with open(state_file, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    if hit is None:
        return None

    level, icon, colour, text = hit
    plain = "%s Context at %d%% (%dk of %dk tokens): %s" % (
        icon, int(pct + 0.5), int(used / 1000.0 + 0.5), win // 1000, text)
    out = {"systemMessage": "\n" + colour + plain + RESET}
    if note:
        out["hookSpecificOutput"] = {"hookEventName": event,
                                     "additionalContext": plain + "\n\n" + NOTES[level]}
    return out


if __name__ == "__main__":
    try:
        result = main(sys.stdin.buffer.read().decode("utf-8", "replace"))
        if result:
            sys.stdout.write(json.dumps(result))  # ASCII-only: no console code page can garble it
    except Exception:
        pass
    sys.exit(0)
