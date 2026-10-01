# context-warning

A coloured warning line in Claude Code when a session's context window fills up.

| Usage | Line | What it means |
|---|---|---|
| 30% | 🟡 yellow | fine for now, keep an eye on it |
| 40% | 🟠 orange | start planning a handoff |
| 50% | 🔴 red | compact or hand off now |

From 30%, the line for the current level shows on every prompt you send, for example:

```
🟠 Context at 43% (430k of 1M tokens): start planning a handoff
```

During tool calls it appears only when a new level is crossed, so a long run still
warns you without repeating on every step. Claude is told once per level, so the
reminder does not use up the context it warns about. Right after `/compact` it stays
quiet until Claude's next reply reports the new usage, and all levels can fire again.

## Install

You need Claude Code and Python 3.10 or later on your PATH. In Claude Code, type:

```
/plugin marketplace add filmuszynski/skills
/plugin install context-warning@filmuszynski-skills
```

Then type `/reload-plugins` (or restart Claude Code).

## Window size

The plugin reads the model from the session's transcript: models with `[1m]` or
"1M context" count as 1,000,000 tokens, others as 200,000. A `/model` switch is picked
up on the next prompt. To force a size, set `CLAUDE_CONTEXT_WINDOW` (in tokens) in the
environment Claude Code starts from.

## Troubleshooting

- **No line at all:** check that `python3 --version` or `python --version` prints 3.10
  or later in the shell Claude Code uses. The hook stays silent on any error, by design.
- **"Hook error" on every prompt:** neither `python3` nor `python` runs in that shell.
  Install Python 3.10+ or put it on the PATH. On macOS without the Command Line Tools,
  `/usr/bin/python3` may ask to install them each time; install them once.
- **No line in a session that was already open when you installed the plugin:** type
  `/reload-plugins` there. `/clear` starts a fresh transcript but does not load new plugins.
- **Two lines per prompt:** an older copy of the hook is still wired up in your own
  `settings.json`. Remove that entry.

State lives in your system temp folder under `claude-context-warn/`, one small file per
session. Nothing leaves your computer.

## License

MIT, see [LICENSE](../../LICENSE).
