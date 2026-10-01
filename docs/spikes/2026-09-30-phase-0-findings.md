# Phase 0 findings (30.09.2026)

Observed on Windows 11, Python 3.13.7, Claude Code with plugin support. macOS and Linux
were not observed in Phase 0; Phase 5 CI is the first place they are exercised.

## 1. Hook launcher

| Variant | Ran? | Interpreter | Notes |
|---|---|---|---|
| A `python` | yes | `python.exe` (3.13) | |
| B `python3` | **no** | none | On Windows `python3` is the Microsoft Store App Execution Alias; it prints "Python was not found" and the hook never runs |
| C `py -3` | yes | `python.exe` (3.13) | The `py` launcher exists only on Windows |
| D `python3 … 2>/dev/null \|\| python …` | yes | `python.exe` (3.13) | Falls through the Store stub to `python` as intended |

A plugin root with spaces works when `${CLAUDE_PLUGIN_ROOT}` is quoted in the command.

**Chosen launcher for Phase 4: D, the chain.** It runs on this Windows machine, and on
macOS and Linux, where `python3` is the normal name and `python` is often missing, the first
half succeeds. Phase 5 CI confirms it on those systems.

## 2. Detached server

- **From a hook:** each of three hook variants spawned the server as `pythonw.exe` with
  `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`. All three were alive well after the hook
  exited, answering `/api/health`. The author watched a second run and saw no window.
- **From a Bash tool call:** the same spawn, run through Claude's Bash tool, left a server
  that was alive after the call returned.
- **Port fallback:** three servers at once landed on 7777, 7778 and 7779, as designed.
- **Problem found:** all three wrote `server.json`, and the last one won. Several renders
  can start at nearly the same moment (one plan write triggers several hooks).

**Chosen spawn method for Phase 2:** `pythonw.exe` next to `sys.executable` on Windows
(falling back to `sys.executable`), `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`, all
three standard streams to `DEVNULL`; `start_new_session=True` on POSIX. **Plus a
single-instance guard:** the server takes an exclusive lock file in `~/.review-doc/`
before binding, and a second instance that cannot take it exits at once.

## 3. Install from a private GitHub repo

Worked. `claude plugin marketplace add filmuszynski/skills` cloned the private repo over
HTTPS with the machine's existing git credentials, and `claude plugin install
review-doc@filmuszynski-skills` installed it. No token setup was needed.

Where the plugin runs from:

- installed from a local folder marketplace: `${CLAUDE_PLUGIN_ROOT}` is **the source
  folder itself**, so edits should take effect without reinstalling (inferred from the path,
  not tested separately);
- installed from GitHub: `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`.

**A new install or reinstall does not reach a running session.** The session keeps its
old hooks until `/reload-plugins` (or a restart). The README must say this right after the
install commands.

All installs and uninstalls in Phase 0 went through the `claude plugin …` command line,
which is scriptable. The in-session `/plugin install` flow was not exercised; only
`/reload-plugins` was typed in a session. Phase 5's acceptance run uses `/plugin` as a new
user would.

## 4. Naming as users see it

- Commands: `/review-doc:review-doc`, `/review-doc:settings`.
- Skills: `review-doc:review-md`, and `review-doc:review-doc`.
- **A command and a skill with the same name collide, and the command wins.** Invoking
  `review-doc:review-doc` ran `commands/review-doc.md`, not the skill. The skill list then
  shows the command's description under that name.

**README and spec wording to use:** `/review-doc:review-doc <file>`, `/review-doc:settings`,
`/review-doc:review-md <file>`. The parent entry point must exist **once**: either as the
skill or as the command, not both. Phase 4 keeps it as the **skill** (skills also trigger on
natural language such as "review this document"), and there is no `commands/review-doc.md`.

## 5. How a skill finds its files

- **Skills:** Claude Code shows a `Base directory for this skill: <absolute path>` line when
  a skill loads. `CLAUDE_PLUGIN_ROOT` is **empty** in the Bash tool's environment.
- **Commands:** `${CLAUDE_PLUGIN_ROOT}` inside a command's text **is substituted** with the
  plugin root before Claude reads it.
- **Hooks:** `CLAUDE_PLUGIN_ROOT` is set in the hook's environment.

**Pattern for Phase 4:** a SKILL.md tells Claude to run the renderer relative to its base
directory, which is `<base>/../../presenter/build_screen.py`. Commands use
`${CLAUDE_PLUGIN_ROOT}/presenter/…`. Hooks use `"${CLAUDE_PLUGIN_ROOT}/…"`, quoted.

## Consequences for later phases

- **Phase 2:** the server needs a single-instance lock (section 2).
- **Phase 4:**
  - the hook launcher is the D chain (section 1);
  - the parent `review-doc` is a skill only, with no command of the same name (section 4);
  - skills locate files from their base directory (section 5).
- **Phase 5:**
  - the README install section adds `/reload-plugins` after installing;
  - the README uses the prefixed names from section 4;
  - CI must run the launcher chain on macOS and Linux.
- **Spec corrections** (made in the private spec, 30.09.2026):
  - the entry point is the `review-doc:review-doc` skill, invoked as
    `/review-doc:review-doc <file>`, with no command of the same name;
  - Windows spawn flags are `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`, not
    `DETACHED_PROCESS`;
  - the server gets a single-instance lock.
- A hook payload without `tool_input.file_path` is handled (logged, exit 0); covered by a
  unit test only.
