---
description: Show or change review-doc settings (how long pages are kept, auto-open, page types)
argument-hint: "[show | set <name> <value> | reset]"
---

Run the review-doc settings command and show the user what it prints.

1. The arguments are: `$ARGUMENTS`. If there are none, use `show`.
2. Run it with `<python>`, which means `python3` on macOS and Linux and `python` on
   Windows (there `python3` is often only the Microsoft Store alias):

   ```bash
   <python> "${CLAUDE_PLUGIN_ROOT}/presenter/settings.py" <arguments>
   ```

3. Show the output in a code block, unchanged. Exit code 2 means the name or value was
   not accepted: show the error line, then this table.

   | Name | Values | Default | What it does |
   |---|---|---|---|
   | `stale-hours` | 1 to 720 | 96 | Pages older than this many hours are deleted, and unsaved comments older than this are dropped |
   | `auto-open` | on, off | on | Opens each new page right after it is rendered |
   | `md` | on, off | on | Markdown document pages |
   | `html` | on, off | on | HTML document pages (they arrive in v1.1) |
   | `plan` | on, off | on | Plan pages, rendered automatically when Claude writes a plan |
   | `choice` | on, off | on | Options and explainer screens |

4. Changes apply at once, with no restart. A page that is already open keeps working
   when its type is switched off; only new pages stop. The same settings are in every
   review page under ⚙ Settings.

Examples: `/review-doc:settings set stale-hours 48`, `/review-doc:settings set plan off`,
`/review-doc:settings reset`.
