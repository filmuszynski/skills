# -*- coding: utf-8 -*-
import io
import os

from harness import test, HERE

import settings

PLUGIN = os.path.dirname(HERE)


def read(*parts):
    with io.open(os.path.join(PLUGIN, *parts), encoding="utf-8") as fh:
        return fh.read()


def front(*parts):
    """Frontmatter as a flat dict of strings, and the body after it."""
    text = read(*parts)
    assert text.startswith("---\n"), parts
    head, body = text[4:].split("\n---\n", 1)
    meta = {}
    for line in head.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"')
    return meta, body


@test
def test_settings_command_wraps_the_cli():
    meta, body = front("commands", "settings.md")
    assert meta.get("description") and "Not yet released" not in meta["description"], meta
    assert meta.get("argument-hint") == "[show | set <name> <value> | reset]", meta
    assert '"${CLAUDE_PLUGIN_ROOT}/presenter/settings.py"' in body
    assert "$ARGUMENTS" in body
    for name in settings.CLI_NAMES:
        assert "`%s`" % name in body, name
    assert "—" not in body
    # The table sits inside list item 3; a row at column 0 ends the item and splits it.
    rows = [l for l in body.splitlines() if l.lstrip().startswith("|")]
    assert rows and all(l.startswith("   |") for l in rows), [l for l in rows if not l.startswith("   |")]


@test
def test_no_command_shadows_a_skill():
    commands = sorted(os.listdir(os.path.join(PLUGIN, "commands")))
    skills = set(os.listdir(os.path.join(PLUGIN, "skills")))
    assert commands == ["settings.md"], commands
    assert not {c[:-3] for c in commands} & skills


SKILLS = ("vet", "review-md", "review-html")


@test
def test_skills_have_real_frontmatter():
    for name in SKILLS:
        meta, body = front("skills", name, "SKILL.md")
        assert meta.get("name") == name, (name, meta)
        d = meta.get("description", "")
        assert len(d) > 120 and "Not yet released" not in d, (name, d)
        # An unquoted YAML value may not hold ": ", or the whole frontmatter fails to parse.
        assert ": " not in d, (name, "colon-space in an unquoted description")
        assert "Placeholder" not in body and "\u2014" not in body, name


@test
def test_skills_find_the_renderer_from_their_base_directory():
    for name in SKILLS:
        _, body = front("skills", name, "SKILL.md")
        assert "<base>/../../presenter/build_screen.py" in body, name
        skill_dir = os.path.join(PLUGIN, "skills", name)
        assert os.path.isfile(os.path.normpath(os.path.join(skill_dir, "..", "..", "presenter", "build_screen.py")))
        assert "CLAUDE_PLUGIN_ROOT" not in body, "empty in the Bash tool (Phase 0 findings, section 5)"
        assert "localhost:" not in body, "links name 127.0.0.1 (ADR 0012)"


@test
def test_vet_is_the_one_command_and_review_md_stays_out_of_the_menu():
    meta, _ = front("skills", "vet", "SKILL.md")
    assert "/vet" in meta["description"], meta
    meta, body = front("skills", "review-md", "SKILL.md")
    assert meta.get("user-invocable") in (False, "false"), meta
    assert "/review-doc:review-md" not in meta["description"] + body
    assert "review-doc:review-doc" not in body
    assert not os.path.exists(os.path.join(PLUGIN, "skills", "review-doc"))


@test
def test_parent_skill_routes_and_handles_every_outcome():
    _, body = front("skills", "vet", "SKILL.md")
    for needle in ("review-doc:review-md", ".markdown", ".html", "review-doc:review-html",
                   "localhost only", "needs-server", "exit 3", "exit 4", "exit 5", "/review-doc:settings set", "offerExtension",
                   "extension.py\" install", "extension.py\" decline",
                   "approved", "revise and re-present", "declined", "CHOSEN:"):
        assert needle in body, needle
    assert "review-doc 1.2" not in body
    assert "The Markdown is never touched" not in body


@test
def test_md_skill_covers_documents_plans_and_screens():
    _, body = front("skills", "review-md", "SKILL.md")
    for needle in ('build_screen.py" doc', 'build_screen.py" plan', 'build_screen.py" screen',
                   "~/.claude/plans/", "archive/", "Never hand-edit", "~/.review-doc/screens/",
                   "kind: options", "kind: explain", "(the text has changed since)"):
        assert needle in body, needle


@test
def test_parent_skill_names_the_real_paste_back_headers():
    meta, body = front("skills", "vet", "SKILL.md")
    for start in ("Review of the plan", "Review of the document", "Review of the HTML page",
                  "Answer to", "Questions on"):
        assert start in meta["description"], start
        assert start in body, start
    assert "Feedback on" not in meta["description"] + body


@test
def test_skills_and_command_never_hard_code_one_python():
    """M4: python3 is often only the Store alias on Windows, python is often missing
    on macOS. Every runnable line names <python>, which the text defines once."""
    texts = {name: front("skills", name, "SKILL.md")[1] for name in SKILLS}
    texts["settings"] = front("commands", "settings.md")[1]
    for name, body in texts.items():
        assert "<python>" in body, name
        for line in body.splitlines():
            assert not line.strip().startswith(("python3 ", "python ")), (name, line)
            assert '`python3 "' not in line and '`python "' not in line, (name, line)


@test
def test_parent_skill_runs_settings_show_itself():
    """M10: Claude cannot type a slash command; it runs the CLI."""
    _, body = front("skills", "vet", "SKILL.md")
    assert 'settings.py" show' in body
    assert "run `/review-doc:settings show`" not in body


@test
def test_review_html_is_not_typed():
    meta, body = front("skills", "review-html", "SKILL.md")
    assert meta.get("user-invocable") in (False, "false"), meta
    assert "/vet" in meta["description"] and ".html" in meta["description"], meta
    assert "/review-doc:review-html" not in meta["description"] + body
    assert 'build_screen.py" html' in body


@test
def test_review_html_skill_covers_addresses():
    _, body = front("skills", "review-html", "SKILL.md")
    for needle in ("Get-NetTCPConnection", "Get-CimInstance", "lsof", "--directory", "curl",
                   "index.html", "only candidate", "ask",
                   "Reviewing a dev server arrives in 1.3. Build or save the page and review the file."):
        assert needle in body, needle


@test
def test_review_html_skill_names_the_generator_rule():
    _, body = front("skills", "review-html", "SKILL.md")
    for needle in ("never edit the output", "report.src.html", "build.py", "next to",
                   "(the element has changed since)", "(already in the page)", "Never hand-edit"):
        assert needle in body, needle


@test
def test_descriptions_mention_html():
    import json
    plugin = json.loads(read(".claude-plugin", "plugin.json"))
    market = json.loads(read("..", "..", ".claude-plugin", "marketplace.json"))
    entry = [p for p in market["plugins"] if p["name"] == "review-doc"][0]
    for d in (plugin["description"], entry["description"]):
        assert "HTML" in d, d
    assert plugin["description"] == entry["description"]


@test
def test_review_html_finds_a_folder_without_directory_and_checks_bytes_on_windows():
    # Final review I1, M4: Windows has no working directory for a process, and
    # curl is an alias of Invoke-WebRequest in Windows PowerShell 5.1.
    _, body = front("skills", "review-html", "SKILL.md")
    for needle in ("Get-ChildItem -Recurse -Filter", "find . -name", "curl.exe", "Get-FileHash"):
        assert needle in body, needle
    assert "`curl -s <address>`" not in body


@test
def test_review_html_checks_for_a_generator_before_editing():
    # Final review I2: the rule needs a step that notices a generated page.
    _, body = front("skills", "review-html", "SKILL.md")
    for needle in ("Before you edit, check whether the file is generated", ".src.", "package.json",
                   "ask which file is the source"):
        assert needle in body, needle


@test
def test_review_html_says_a_changed_element_was_not_found():
    # Final review M6: step 0 is a pill, the item was not found.
    _, body = front("skills", "review-html", "SKILL.md")
    assert "found only by its text" not in body
    assert "was not found on the page any more" in body


@test
def test_vet_follows_the_addresses_a_static_server_prints():
    # Final review M5: http.server prints http://[::]:8000/ or http://0.0.0.0:8000/.
    _, body = front("skills", "vet", "SKILL.md")
    for needle in ("`0.0.0.0`", "`[::]`", "`*.localhost`"):
        assert needle in body, needle
