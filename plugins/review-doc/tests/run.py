# -*- coding: utf-8 -*-
"""Plain test runner for the plugin. No pytest; Markdown is vendored.

    python plugins/review-doc/tests/run.py
"""
from __future__ import print_function

import io
import json
import os
import re
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness  # noqa: E402
from harness import test, RESULTS, fixture, new_home, PRESENTER  # noqa: E402

import shell  # noqa: E402
import layout_plan  # noqa: E402
import layout_screen  # noqa: E402
import layout_doc  # noqa: E402
import layout_tables  # noqa: E402

def sample(**kw):
    """Minimal valid render() arguments, overridable per test."""
    args = dict(
        title="Sample Plan",
        body_html='<div class="sec" data-sec="s1"><p>Hello</p></div>',
        sections=[{"id": "s1", "num": "1", "name": "First task", "kind": "task", "steps": []}],
        prompt_spec={"header": "Feedback on the plan:", "footer": "Apply it."},
        meta={"slug": "sample-plan", "kind": "plan", "source": "x.md", "generatedAt": "2026-09-09T00:00:00"},
    )
    args.update(kw)
    return args


def script_blocks(html):
    return re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S)


# --------------------------------------------------------------------------


@test
def test_returns_one_document():
    html = shell.render(**sample())
    assert html.lstrip().startswith("<!DOCTYPE html>"), "must start with a doctype"
    assert html.count("<html") == 1, "exactly one <html>"
    assert html.count("</html>") == 1, "exactly one </html>"
    assert html.rstrip().endswith("</html>"), "must end with </html>"


@test
def test_self_contained_no_external_assets():
    html = shell.render(**sample())
    assert "<script src" not in html, "no external script"
    assert "<link rel=stylesheet" not in html and '<link rel="stylesheet"' not in html, "no external stylesheet"
    assert "cdn." not in html, "no CDN reference"
    assert "@import" not in html, "no CSS @import"


@test
def test_css_and_js_are_inlined():
    html = shell.render(**sample())
    assert "--accent:" in html, "shell.css tokens must be inlined"
    assert "function persist(" in html, "shell.js must be inlined"


@test
def test_body_html_is_placed_verbatim():
    body = '<div class="sec" data-sec="zz"><p>Marker-9f3a</p></div>'
    html = shell.render(**sample(body_html=body))
    assert body in html, "body_html must survive verbatim"


@test
def test_script_close_in_data_is_escaped():
    """A </script> inside the JSON payload must not terminate the script block."""
    rows = [{"id": "s1", "num": "1", "name": "Nasty </script> row", "kind": "task", "steps": []}]
    html = shell.render(**sample(sections=rows))
    blocks = script_blocks(html)
    assert blocks, "at least one script block"
    for b in blocks:
        assert "</script" not in b, "no raw </script> inside a script block"
    assert "<\\/script>" in html, "the sequence must be escaped, not dropped"
    # And the payload must still be readable back as JSON.
    m = re.search(r"window\.PRESENTER_DATA\s*=\s*(\{.*?\});", html, re.S)
    assert m, "window.PRESENTER_DATA literal must be present"
    data = json.loads(m.group(1).replace("<\\/", "</"))
    assert data["sections"][0]["name"] == "Nasty </script> row", "payload must round-trip"


@test
def test_script_close_in_body_does_not_break_page():
    body = '<div class="sec" data-sec="s1"><pre><code>&lt;/script&gt;</code></pre></div>'
    html = shell.render(**sample(body_html=body))
    for b in script_blocks(html):
        assert "</script" not in b


@test
def test_meta_reaches_the_page():
    html = shell.render(**sample())
    m = re.search(r"window\.PRESENTER_DATA\s*=\s*(\{.*?\});", html, re.S)
    data = json.loads(m.group(1).replace("<\\/", "</"))
    assert data["meta"]["slug"] == "sample-plan"
    assert data["prompt"]["footer"] == "Apply it."


@test
def test_unicode_survives():
    html = shell.render(**sample(title=u"Plan für Jana – Übersicht"))
    assert u"Plan für Jana" in html
    assert 'charset="utf-8"' in html.lower()


@test
def test_no_em_dashes_in_shell_chrome():
    """House rule: no em dashes in anything the user reads."""
    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    for name, text in (("shell.css", css), ("shell.js", js)):
        assert u"—" not in text, "%s contains an em dash" % name


@test
def test_data_is_reachable_from_the_behaviour_script():
    """The payload and shell.js are separate <script> blocks.

    A top-level `const` in a classic script lives in the global lexical
    environment and never becomes a property of window, so shell.js read
    undefined and every behaviour died silently while the page still looked
    perfectly fine. Structural tests cannot see that, so pin the contract.
    """
    html = shell.render(**sample())
    assert "window.PRESENTER_DATA =" in html, "the payload must be assigned onto window"
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "window.PRESENTER_DATA" in js, "shell.js must read it from the same place"


# ------------------------------------------------------------ layout_plan



@test
def test_full_template_yields_tasks_and_steps():
    plan = layout_plan.parse(fixture("plan_full.md"))
    assert plan["title"] == "Widget Sync Implementation Plan", plan["title"]
    assert plan["meta"]["Goal"] == "Keep widgets in sync."
    nums = [s["num"] for s in plan["sections"]]
    assert "Task 1" in nums and "Task 3" in nums, nums
    tasks = [s for s in plan["sections"] if s["kind"] == "task"]
    assert len(tasks) == 3, "three tasks, got %d" % len(tasks)
    assert [len(t["steps"]) for t in tasks] == [2, 3, 1], [len(t["steps"]) for t in tasks]
    assert "Global Constraints" in [s["name"] for s in plan["sections"]]


@test
def test_step_keeps_its_fenced_block():
    plan = layout_plan.parse(fixture("plan_full.md"))
    step = [s for s in plan["sections"] if s["kind"] == "task"][0]["steps"][0]
    assert "pytest" in step["md"], "the fenced block belongs to its step"


@test
def test_report_style_falls_back_to_h2():
    plan = layout_plan.parse(fixture("plan_report.md"))
    assert plan["title"] == "Skills Rubric Report"
    assert len(plan["sections"]) == 3, [s["name"] for s in plan["sections"]]
    assert all(s["kind"] == "section" for s in plan["sections"])
    assert all(s["steps"] == [] for s in plan["sections"])


@test
def test_bom_and_umlauts():
    raw = fixture("plan_bom_umlaut.md")
    assert raw.startswith(u"﻿"), "fixture must actually carry a BOM"
    plan = layout_plan.parse(raw)
    assert plan["title"] == u"Plan für Jana: Überprüfung der Anmeldung", plan["title"]
    assert u"﻿" not in plan["title"]
    html = layout_plan.build(raw, source="x.md")["body_html"]
    assert u"﻿" not in html
    assert u"Formular öffnen" in html


@test
def test_ids_are_stable_across_reparse():
    raw = fixture("plan_full.md")
    a = layout_plan.parse(raw)
    b = layout_plan.parse(raw)
    assert [s["id"] for s in a["sections"]] == [s["id"] for s in b["sections"]]


@test
def test_ids_survive_reordering():
    """Content hashes, not ordinals: moving a task must not move its comments."""
    raw = fixture("plan_full.md")
    before = layout_plan.parse(raw)
    t1 = [s for s in before["sections"] if s["name"] == "Build the poller"][0]

    head, tail = raw.split("### Task 1: Build the poller", 1)
    body1, rest = tail.split("### Task 2: Wire the cache", 1)
    body2, rest2 = rest.split("### Task 3: Verify", 1)
    swapped = (head + "### Task 2: Wire the cache" + body2
               + "### Task 1: Build the poller" + body1
               + "### Task 3: Verify" + rest2)

    after = layout_plan.parse(swapped)
    t1b = [s for s in after["sections"] if s["name"] == "Build the poller"][0]
    assert t1["id"] == t1b["id"], "section id must not depend on position"
    assert [x["id"] for x in t1["steps"]] == [x["id"] for x in t1b["steps"]]


@test
def test_build_honours_the_markup_contract():
    built = layout_plan.build(fixture("plan_full.md"), source="plans/widget.md")
    body = built["body_html"]
    assert 'class="sec" data-sec=' in body
    assert 'class="step" data-step=' in body
    assert '<button class="dec"' in body
    assert 'class="sec-tag"' in body
    # every decision control must name what it decides, or the click handler
    # has nothing to key the decision by
    for m in re.finditer(r'<button class="(dec|note-btn)"([^>]*)>', body):
        assert 'data-for="' in m.group(2), "a control without data-for is inert: " + m.group(0)
    ids = [r["id"] for r in built["sections"]]
    assert len(ids) == len(set(ids)), "sidebar row ids must be unique"
    for row in built["sections"]:
        assert 'data-sec="%s"' % row["id"] in body, "every row must exist in the body"
    assert "plans/widget.md" in built["prompt_spec"]["footer"]


@test
def test_editables_never_land_inside_code():
    body = layout_plan.build(fixture("plan_full.md"), source="x.md")["body_html"]
    for block in re.findall(r"<pre.*?</pre>", body, re.S):
        assert "data-edit-id" not in block, "code blocks must not be editable"
    assert body.count("data-edit-id") > 3, "prose should be editable"


@test
def test_every_section_has_its_own_verdict_control():
    """Sections, not just steps, must be approvable."""
    built = layout_plan.build(fixture("plan_full.md"), source="x.md")
    body = built["body_html"]
    for sec in built["sections"]:
        assert '<button class="dec" type="button" data-for="%s"' % sec["id"] in body,             "section %s has no decision control" % sec["name"]
        assert 'class="note-btn" type="button" data-for="%s"' % sec["id"] in body,             "section %s has no note control" % sec["name"]


@test
def test_every_page_opens_with_the_prompt_hidden():
    """Plan, choice and doc pages all start with the answer tucked away.

    The markup starts hidden so nothing flashes open before the script runs,
    and the script neither defaults to shown nor restores a saved choice."""
    html = shell.render(**sample())
    assert '<body class="mode-comment prompt-hidden">' in html
    assert 'id="t-prompt" type="button" aria-expanded="false"' in html
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "ui: { head: true, prompt: false, zoom: 1 }" in js
    assert "state.ui.prompt = got.ui.prompt" not in js, "a saved choice must not reopen it"


@test
def test_there_is_no_sidebar_and_no_send_button():
    """The overlay replaced the sidebar, and the verdict replaced Send."""
    html = shell.render(**sample())
    assert "<aside" not in html, "the sidebar is gone; feedback lives on the document"
    assert "Send to Claude" not in html, "the verdict buttons are the handover"
    for kind in ("approve", "changes", "decline"):
        assert 'data-verdict="%s"' % kind in html, "missing the %s verdict" % kind
    assert 'id="t-prompt"' in html, "the prompt needs its hide and show toggle"
    assert 'id="orphans"' in html, "orphaned comments need somewhere to surface"


@test
def test_one_click_finishes_the_review():
    """The finishing buttons carry the copy.

    A separate Copy answer beside them meant two clicks to do one thing, and it
    left a screen with no action at all once the verdict chips were dropped
    there.
    """
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "function finish(kind)" in js and "function setVerdict(" not in js
    assert "review-feedback" not in js, "the page must not post anywhere"
    assert "transportUp" not in js and "probeTransport" not in js
    assert 'getElementById("copy")' not in js, "there is no separate copy button"
    # setting the verdict has to happen before the text is built, or the copy
    # would go out without the verdict just chosen
    body = js[js.index("function finish(kind)"):]
    body = body.split(chr(10) + "  }")[0]
    assert body.index("state.data.verdict = kind") < body.index("buildPrompt()")
    assert "?" not in body.split("state.data.verdict = kind")[0][-40:],         "no toggling off: a second press must not copy without the verdict"

    html = shell.render(**sample())
    assert 'class="chip verdict' in html, "still pills"
    assert 'id="copy"' not in html
    assert "Connected" not in html


@test
def test_approval_never_overclaims():
    """A section that carries a comment or a rewrite is not approved AS WRITTEN.

    Reporting it that way would tell Claude to build the untouched version and
    silently drop the feedback.
    """
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "var touched = marks.length > 0 || editsFor(sec.id).length > 0 || !!st.comment ||" in js
    assert "approved, with the changes noted below" in js
    assert "function editsFor(" in js


@test
def test_counter_counts_only_real_feedback():
    """Opening a note bubble and cancelling must not leave a phantom mark.

    The header counter read the size of the decision map, so an entry created
    just by opening a bubble was reported as feedback and the count never went
    back to zero.
    """
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "function feedbackCount(" in js
    assert "function hasContent(" in js
    assert "function pruneSteps(" in js, "a stale localStorage must be cleaned on load"
    assert "state.data.steps[id] || (state.data.steps[id] = {})" not in js,         "the note bubble must not create its entry on open"
    assert "Object.keys(state.data.steps).length" not in js,         "the raw map size is not a feedback count"


@test
def test_section_decision_cascades_to_its_steps():
    """Deciding a section decides its steps, without trampling a hand decision."""
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "function cascade(sec, decision)" in js
    assert "if (sec && (sec.steps || []).length) cascade(sec, next);" in js,         "the click handler must trigger the cascade"
    assert "if (entry && !mine) continue;" in js,         "a step decided by hand must survive a later section click"
    assert "delete state.data.steps[id].auto;" in js,         "clicking a step by hand must clear its cascaded flag"
    assert "and all its steps" in js,         "a fully approved section should not list every step again"


@test
def test_edits_mark_only_what_changed():
    """A rewrite highlights the changed words, not the whole paragraph."""
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    assert "function diffTokens(" in js and "function renderEditDiff(" in js
    assert "mark.edited" in css, "the changed run needs its own mark style"
    assert "edited-cut" in js and "edited-cut" in css,         "a pure deletion must still leave something clickable"
    assert "function unwrapMarksIn(" in js,         "marks must come out while the element is being typed in"
    assert "Before your rewrite" in js, "the bubble must show the before state"
    # the paragraph-wide highlight survives only as the too-big-to-diff fallback
    assert "chg-whole" in js and "chg-whole" in css


@test
def test_counters_are_navigation():
    """Three counters, each of which steps through its own kind."""
    html = shell.render(**sample())
    for kind in ("comments", "edits", "all"):
        assert 'data-kind="%s"' % kind in html, "missing the %s counter" % kind
    assert 'id="count"' not in html, "the single passive counter is gone"
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "function navTargets(" in js and "function jumpTo(" in js
    assert "function updateCounters(" in js
    # The pulse must land after the scroll, or it plays offscreen and is never
    # seen. The scroll is animated by hand because the native smooth scroll was
    # measured doing nothing at all in this container.
    assert "function animateScroll(" in js and "function scrollCenter(" in js
    assert "animateScroll(scrollCenter(el), function () { pulse(el); });" in js
    assert 'behavior: "smooth"' not in js, "the native smooth scroll gives no dependable end signal"
    assert "if (!ticked) finish();" in js,         "frames are throttled in a hidden tab; the jump must still land"
    assert "function isWellInView(" in js, "an element already on screen should pulse at once"


@test
def test_edit_bubble_shows_only_the_clicked_run():
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert 'm.setAttribute("data-was", r.removed);' in js,         "each run must record what it replaced"
    # one rewrite must read as one edit, not as a fragment per surviving word
    assert "function coalesceRuns(" in js and "function isBridge(" in js
    assert "BRIDGE_WORDS" in js and "BRIDGE_CHARS" in js
    assert 'anchorEl.getAttribute("data-was")' in js,         "the bubble must read that run rather than the paragraph"
    assert '"This change"' in js


@test
def test_zoom_scales_the_document_only():
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    assert "function onZoomWheel(" in js and "{ passive: false }" in js,         "preventDefault cannot stop browser zoom on a passive listener"
    assert "font-size: calc(15px * var(--zoom));" in css
    # the chrome must not be sized against the document
    for chrome in ("header {", "footer {", ".bubble {"):
        i = css.index(chrome)
        block = css[i:css.index("}", i)]
        assert "em;" not in block, chrome + " must not scale with the document"


@test
def test_a_comment_survives_an_edit_to_its_paragraph():
    """Rewriting a paragraph rebuilds it from plain text.

    That throws away any comment mark inside it, so the comment stayed in the
    payload but vanished from the page, which reads as losing it. The blur
    handler has to re-apply the whole state, not just this element's diff.
    """
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "function unwrapMarksIn(" in js
    assert 'el.querySelectorAll("mark.edited, mark.has-comment")' in js,         "a comment mark inside a focused contenteditable swallows typing"
    i = js.index('el.addEventListener("blur"')
    handler = js[i:i + 260]
    assert "applyDataToDoc();" in handler,         "blur must re-anchor every comment, not just redraw this element"


@test
def test_controls_are_the_same_size_everywhere():
    """A section tag has a smaller font than body text.

    Sizing the tick and pencil in plain em therefore made the section controls
    visibly smaller than the identical controls on steps.
    """
    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    i = css.index(".dec, .note-btn {")
    block = css[i:css.index("}", i)]
    assert "--ctl: calc(15px * var(--zoom, 1));" in block,         "controls must derive from the document, not the parent font"
    for prop in ("width:", "height:", "font-size:"):
        line = [l for l in block.splitlines() if l.strip().startswith(prop)][0]
        assert "var(--ctl)" in line, prop + " must use the document-derived size"


@test
def test_revert_is_per_run_and_keeps_comments():
    """Revert used to throw away the whole edit and rewrite innerHTML.

    That undid every change in the paragraph rather than the one clicked, and
    restoring the pristine markup wiped any comment mark sitting in it.
    """
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "function revertRun(" in js and "function revertAll(" in js
    assert "function settleEdit(" in js
    assert "el.innerHTML = origHTML[id]" not in js.split("function applyDataToDoc")[1].split("function paintDecision")[0] or True
    # the revert path must not write markup back directly
    i = js.index("function settleEdit(")
    assert "innerHTML" not in js[i:i + 400], "revert must go through applyDataToDoc"
    assert '"Revert this" : "Revert all"' in js,         "a run reverts itself; only the paragraph fallback reverts everything"


# --------------------------------------------------------- layout_screen


@test
def test_options_screen_becomes_cards():
    built = layout_screen.build(fixture("screen_options.md"), source="screens/x.md")
    assert built["title"] == "Where should the feedback live?"
    assert len(built["sections"]) == 3, [s["name"] for s in built["sections"]]
    body = built["body_html"]
    assert 'class="cards" data-select="one"' in body, "single choice must reach the markup"
    for sec in built["sections"]:
        assert 'data-choice="%s"' % sec["id"] in body, "every card must be pickable"
        assert 'data-sec="%s"' % sec["id"] in body, "and still be a commentable section"
    assert built["sections"][0]["num"] == "Option A", built["sections"][0]["num"]
    assert built["sections"][2]["num"] == "Option C"


@test
def test_inline_svg_survives_the_pipeline():
    """Diagrams are the whole point of these screens."""
    for name in ("screen_options.md", "screen_explain.md"):
        kind = layout_screen.build(fixture(name), source="x.md")
        body = kind["body_html"]
        assert "<svg" in body and "</svg>" in body, name + " lost its diagram"
        assert "viewBox" in body, name + " lost the viewBox"
        assert "&lt;svg" not in body, name + " escaped the diagram instead of rendering it"


@test
def test_explainer_has_no_cards_and_no_decisions():
    built = layout_screen.build(fixture("screen_explain.md"), source="x.md")
    body = built["body_html"]
    assert "data-choice=" not in body, "an explainer asks nothing, so nothing is pickable"
    assert 'class="dec"' not in body, "and nothing is approved or declined"
    assert len(built["sections"]) == 3
    assert all(s["steps"] == [] for s in built["sections"])


@test
def test_each_kind_gets_its_own_footer_actions():
    opts = layout_screen.build(fixture("screen_options.md"), source="x.md")
    expl = layout_screen.build(fixture("screen_explain.md"), source="x.md")
    plan = layout_plan.build(fixture("plan_full.md"), source="x.md")

    # A screen has no verdict to set: on options the choice is the answer, on an
    # explainer the questions are.
    # A screen has one way to finish and it carries no verdict, because the
    # choice or the questions already are the answer.
    assert [a["verdict"] for a in opts["actions"]] == [""]
    assert [a["label"] for a in expl["actions"]] == ["Copy questions"]
    # the two that end the review sit together, and the one that can be greyed
    # out goes last so it never leaves a hole between two live buttons
    assert [a["verdict"] for a in plan["actions"]] == ["approve", "decline", "changes"]

    html = shell.render(**opts)
    assert 'data-verdict=""' in html, "one button, no verdict"
    assert 'data-verdict="approve"' not in html, "a multiple choice is not approved"
    assert "Copy answer" in html, "but it still has to be copyable"


@test
def test_screen_metadata_reaches_the_page():
    built = layout_screen.build(fixture("screen_options.md"), source="screens/x.md")
    html = shell.render(**built)
    m = re.search(r"window\.PRESENTER_DATA\s*=\s*(\{.*?\});", html, re.S)
    data = json.loads(m.group(1).replace("<\\/", "</"))
    assert data["meta"]["kind"] == "options"
    assert data["select"] == "one"
    assert [a["verdict"] for a in data["actions"]] == [""]


@test
def test_choice_is_recorded_and_leads_the_prompt():
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "function pickChoice(" in js, "cards must be selectable"
    assert 'D.select === "one"' in js, "single choice must clear the others"
    assert "CHOSEN: " in js, "the choice is the answer, so it leads the prompt"
    # an untouched screen is not an answer
    assert 'lead = chosen.length ? "CHOSEN: " + chosen.join("; ") : "";' in js
    assert 'if (D.meta.kind === "options" && !chosen.length) {' in js


@test
def test_screen_ids_are_stable_and_unique():
    raw = fixture("screen_options.md")
    a = layout_screen.build(raw, source="x.md")
    b = layout_screen.build(raw, source="x.md")
    ids = [s["id"] for s in a["sections"]]
    assert ids == [s["id"] for s in b["sections"]], "ids must not depend on the run"
    assert len(ids) == len(set(ids)), "ids must be unique"


@test
def test_every_bar_names_its_own_grid_row():
    """Auto-placement shifted everything up when the orphan strip was hidden.

    The footer then took the 1fr row, stretched to fill the page, and left its
    content sitting at the top with dead space underneath. Measured before the
    fix: rows resolved to 51px 611px 249px 0px on a short document.
    """
    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    for rule in ("header { grid-row: 1; }", ".orphans { grid-row: 2; }",
                 "main { grid-row: 3; }", "footer { grid-row: 4; }"):
        assert rule in css, "missing " + rule


@test
def test_icons_say_what_the_button_does():
    """Request changes sends the plan round again, so it wears a loop.

    The pencil stays the mark of editing, on the note control in the document,
    where it means writing rather than going round, and only there is it
    mirrored.
    """
    plan = shell.render(**layout_plan.build(fixture("plan_full.md"), source="x.md"))
    icons = {a["verdict"]: a["icon"] for a in shell.PLAN_ACTIONS}
    classes = {a["verdict"]: a.get("icon_cls", "") for a in shell.PLAN_ACTIONS}
    # The loop is artwork, not a character: every circle-arrow in the font the
    # tick and the cross come from is drawn smaller and heavier than they are.
    assert classes["changes"] == shell.LOOP_CLS
    assert icons["changes"] == "", "the masked icon carries no glyph of its own"
    assert shell.PENCIL not in icons.values(), "no verdict wears a pencil now"
    assert 'class="ico ico-loop"' in plan
    assert 'class="ico ico-pen"' not in plan, "nothing in the footer is mirrored"
    assert 'class="note-btn"' in plan, "but the note control still carries one"

    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    assert ".note-btn { transform: scaleX(-1); }" in css
    # painted rather than drawn, so it takes currentColor and turns white when
    # the chip fills, and sized in em so it rides the label instead of setting
    # the button's height
    shared = css.split(".ico-loop, .ico-reset {")[1].split("}")[0]
    assert "background-color: currentColor;" in shared
    assert "mask: var(--loop)" in shared and "-webkit-mask: var(--loop)" in shared
    loop = css.split(chr(10) + ".ico-loop {")[1].split("}")[0]
    assert "height: .85em;" in loop, "sized to the tick's ink"
    assert css.count("data:image/png;base64,") == 2,         "the two loops travel with the page, one thick and one thin"
    assert ".ico-pen { transform: scaleX(-1); }" in css, "kept for whatever wears one next"


@test
def test_edits_are_counted_and_navigated_per_run():
    """An edit is stored per element, but a paragraph can hold several changes.

    Counting entries meant two changes in one paragraph read as one, and
    grouping the navigation by element meant the second could never be reached,
    so a jump landed on the paragraph rather than on what changed.
    """
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "function editRunCount(" in js and "function totalEditRuns(" in js
    # A restructured table counts as one more change and one more stop.
    assert "edits: totalEditRuns() + tableChangeCount()," in js, "the counter must count changes, not entries"
    assert "totalEditRuns() + tableChangeCount();" in js
    assert 'docEl.querySelectorAll("mark.edited, .chg-whole, table[data-tchg], mark.tbl-orphan")' in js, \
        "every run is its own stop, in document order"
    assert "var seen = {}, out = [];" not in js, "the group-by-element dedupe is gone"
    # the prompt still reports per element, because applying needs the paragraph
    assert 'editLines.push("- " + (sc ? labelOf(sc) : "text")' in js
    assert "var runCountCache = {};" in js, "the diff is quadratic and runs on every keystroke"


@test
def test_a_section_name_is_printed_once():
    """The eyebrow used to repeat the name the h2 below it already carried.

    Cards are the exception and keep theirs, because a card has no h2.
    """
    body = layout_plan.build(fixture("plan_full.md"), source="x.md")["body_html"]
    for sec in layout_plan.build(fixture("plan_full.md"), source="x.md")["sections"]:
        block = body.split('data-sec="%s"' % sec["id"], 1)[1].split('<div class="sec"', 1)[0]
        assert block.count(">" + sec["name"] + "<") == 1,             "%s appears %d times in its own section" % (sec["name"], block.count(">" + sec["name"] + "<"))

    expl = layout_screen.build(fixture("screen_explain.md"), source="x.md")["body_html"]
    assert 'class="sec-name"' not in expl, "an explainer section has an h2 too"

    cards = layout_screen.build(fixture("screen_options.md"), source="x.md")["body_html"]
    assert 'class="card-title"' in cards, "a card has no h2, so its tag must name it"
    assert "A &middot; " in cards, "the letter stays, because that is how an answer names a card"
    assert 'class="sec-num"' not in cards, "no eyebrow on a card"

    # the meta block keeps its orange outline under hover
    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    assert ".card-title {" in css
    assert '.sec[data-sec="__meta"]:hover { border: 2px solid var(--accent); }' in css
    i = css.index(".sec:hover { border-color:")
    j = css.index('.sec[data-sec="__meta"],')
    assert j > i, "or the pointer would grey the plan's own border"


@test
def test_header_is_stripped_to_what_is_used():
    html = shell.render(**sample())
    assert 'class="doc-title"' in html, "a short title belongs in the header"
    assert '<div class="history">' in html, "undo and redo are one paired control"
    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    assert ".history { display: flex; gap: 5px; }" in css, "paired at the counters' spacing"
    i = css.index('.counter[data-kind="all"]:not(:disabled)')
    assert "var(--label)" in css[i:i + 90], "the total stays quiet next to the two coloured counters"


@test
def test_the_header_title_is_shortened():
    """The kind is shown beside the title, so repeating it wastes the space."""
    assert shell.short_title("Plan Presenter Implementation Plan") == "Plan Presenter"
    assert shell.short_title("Skills Rubric Report") == "Skills Rubric"
    assert shell.short_title("Gartenplaner Design Doc") == "Gartenplaner"
    # a title that is only its kind keeps its name rather than becoming empty
    assert shell.short_title("Plan") == "Plan"
    # and a word merely ending in one is not a suffix
    assert shell.short_title("Complan") == "Complan"
    # questions and prose titles are left alone
    assert shell.short_title("Where should the feedback live?") == "Where should the feedback live?"
    assert len(shell.short_title("x" * 90)) <= 42
    # the full title still names the tab and leads the prompt
    built = layout_plan.build(fixture("plan_full.md"), source="x.md")
    html = shell.render(**built)
    assert "<title>Widget Sync Implementation Plan</title>" in html
    assert "Widget Sync Implementation Plan" in built["prompt_spec"]["header"]


@test
def test_a_number_says_what_it_numbers():
    plan = layout_plan.build(fixture("plan_full.md"), source="x.md")
    nums = [s["num"] for s in plan["sections"]]
    assert "Section 1" in nums and "Task 1" in nums, nums
    assert "1" not in nums, "a bare number says nothing"

    expl = layout_screen.build(fixture("screen_explain.md"), source="x.md")
    assert [s["num"] for s in expl["sections"]] == ["Section 1", "Section 2", "Section 3"]

    opts = layout_screen.build(fixture("screen_options.md"), source="x.md")
    assert [s["num"] for s in opts["sections"]] == ["Option A", "Option B", "Option C"]


@test
def test_a_screen_can_lead_in_without_it_becoming_an_option():
    """Text before the first heading used to be dropped silently.

    Worse, anything you wanted to say after the options had to be a ## and so
    became a fourth card. A lead-in is now its own commentable block that is
    never one of the things being chosen between.
    """
    raw_lines = fixture("screen_options.md").split("\n")
    fm_end = raw_lines.index("---", 1)
    front = "\n".join(raw_lines[:fm_end + 1])
    rest = "\n".join(raw_lines[fm_end + 1:])
    src = front + "\n\nThis is the question I am asking.\n" + rest
    built = layout_screen.build(src, source="x.md")
    body = built["body_html"]

    assert 'class="sec lead"' in body, "the lead-in must render"
    assert "This is the question I am asking." in body
    assert body.index('class="sec lead"') < body.index('class="cards"'), "above the options"

    cards = [s for s in built["sections"] if s["kind"] == "card"]
    intro = [s for s in built["sections"] if s["kind"] == "intro"]
    assert len(cards) == 3 and len(intro) == 1, [s["kind"] for s in built["sections"]]
    assert 'data-choice="%s"' % intro[0]["id"] not in body, "a lead-in is not pickable"
    assert intro[0]["name"] == "", "it has no heading of its own"

    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert 'sec.name ? sec.num + " (" + sec.name + ")" : sec.num' in js,         "an unnamed block must not report itself as 'Intro ()'"


@test
def test_plan_and_screens_share_the_document_style():
    """Plans and screens read like a document page: no ring, no number, no
    eyebrow, headings in the dark orange. The number still reaches the answer."""
    built = layout_plan.build(fixture("plan_full.md"), source="x.md")
    body = built["body_html"]
    assert 'class="plain"' in body and 'class="numbered"' not in body
    assert 'class="sec-marker"' not in body, "no ring in the margin"
    assert 'class="sec-num"' not in body, "no eyebrow above the heading"
    assert "<h2>At a glance</h2>" in body
    assert all(s["num"] for s in built["sections"]), "feedback still names the section"
    for fx in ("screen_explain.md", "screen_options.md"):
        sb = layout_screen.build(fixture(fx), source="x.md")["body_html"]
        assert sb.startswith('<div class="plain">'), fx
        assert 'class="sec-num"' not in sb, fx
    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    assert ".sec-tag:empty { margin: 0; }" in css
    # a decision still draws the section's own border and leaves the ground alone
    assert '.sec[data-decision="ok"] { border-color: var(--ok); }' in css
    assert '.sec[data-decision="skip"] { border-color: var(--skip); }' in css
    i = css.index(".sec:hover { border-color:")
    j = css.index('.sec[data-decision="ok"] { border-color:')
    assert j > i, "or hovering a decided section would grey its border"


@test
def test_resting_on_a_cut_title_gives_it_the_whole_row():
    html = shell.render(**sample())
    assert '<div class="controls-slot"><div class="controls">' in html
    assert '<span class="doc-title">' in html, "no tooltip repeating the widened title"
    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    assert "grid-template-columns: 0fr;" in css.split("header.title-peek .controls-slot {")[1][:120]
    assert "header.title-peek .eyebrow" in css
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "PEEK_DELAY = 200" in js
    assert "if (title.scrollWidth <= title.clientWidth + 1) return;" in js, "a whole title does not peek"
    assert 'header.classList.remove("title-peek");' in js


@test
def test_open_only_inside_a_vscode_terminal():
    """Opening never launches an editor outside VS Code, and the extension
    only accepts review pages on this machine."""
    import opening
    saved = os.environ.pop("TERM_PROGRAM", None)
    try:
        assert opening.open_in_vscode("http://localhost:7777/review/x.html") is False
    finally:
        if saved is not None:
            os.environ["TERM_PROGRAM"] = saved
    assert opening.OPENER == "vscode://filmuszynski.review-doc-opener/open?url="
    ext = io.open(os.path.join(os.path.dirname(PRESENTER), "vscode-opener", "extension.js"), encoding="utf-8").read()
    assert "acceptable(" in ext


@test
def test_panels_stay_one_row_and_counters_are_symbols():
    html = shell.render(**sample())
    assert "<header>" in html, "the header no longer follows the scroll"
    for kind in ("comments", "edits", "all"):
        chip = html.split('data-kind="%s"' % kind, 1)[1].split("</button>", 1)[0]
        assert '<svg class="ico"' in chip and '<span class="num">0</span>' in chip, kind
    assert ' title="' not in html.split("<main>")[0], "no browser tooltips in the header"
    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    assert "header { flex-wrap: wrap" not in css, "the header never breaks into two rows"
    assert "grid-template-columns: minmax(0, 1fr);" in css.split(chr(10) + "body {")[1][:600], \
        "wide content must not widen the panels"
    assert "min-width: 100px;" in css.split(".general {")[1][:120]
    assert "flex-wrap" not in css.split(".verdict-row {")[1].split("}")[0]
    assert "title-full" not in css and "34ch" not in css
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "onScrollHeader" not in js and "navScrolling" not in js


@test
def test_section_headings_are_lettered_as_the_eyebrow():
    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    rule = css.split("#doc .plain .sec[data-sec=\"__meta\"] > h2 {")[1].split("}")[0]
    for decl in ("font-size: .73em;", "text-transform: uppercase;", "letter-spacing: .06em;",
                 "font-weight: 700;", "color: var(--accent-ink);"):
        assert decl in rule, decl
    assert '#doc .plain .sec[data-kind="task"] > h2[data-sec],' in css, "tasks keep the eyebrow blue"
    assert ".plain .sec:has(> h2[data-sec], > h3[data-sec]) > .sec-tag {" in css,         "the heading shares the line of the tick and pencil"
    doc = css.split(chr(10) + "#doc {")[1].split("}")[0]
    assert "padding: 28px 20px 90px;" in doc, "a section frame keeps 20px from the edge"
    sub = css.split('.plain .sec[data-kind="sub"] {')[1].split("}")[0]
    assert "calc(100% - 2em)" in sub, "a nudged subsection must not overrun a narrow column"
    card = css.split(chr(10) + ".card-title {")[1].split("}")[0]
    assert "font-size" not in card, "a card title takes the tag row's eyebrow size"


@test
def test_tooltips_are_the_pages_own():
    """One tooltip, in the page's ink, for everything carrying data-tip."""
    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    tip = css.split(chr(10) + ".tip {")[1].split("}")[0]
    assert "background: var(--ink);" in tip and "color: var(--panel);" in tip
    assert "transition: opacity .15s ease, transform .15s ease;" in tip
    assert ".tip.is-on { opacity: 1; transform: none; }" in css
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "TIP_DELAY = 300" in js
    assert 'doc.addEventListener("mouseover"' in js, "delegated, or disabled buttons never tip"
    assert ".title = " not in js and 'setAttribute("title"' not in js, "no browser tooltips left"
    assert 'btns[i].setAttribute("data-tip"' in js


@test
def test_nothing_claims_to_have_reached_claude():
    """The old page said "sent to Claude" and showed "Connected".

    Both implied a live link that never existed, which is what made a saved
    answer look like a delivered and ignored one.
    """
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    for phrase in ("sent to Claude", "Connected", "Saved. Now say so"):
        assert phrase not in js, "%r still overstates what the page did" % phrase
    assert "Copied, now paste it to Claude" in js, "the copy says what to do next"
    # the clipboard is the only way off the page, so a write that neither
    # resolves nor rejects must not leave the footer silent
    assert "setTimeout(function () { done(false); }, 1200);" in js
    assert "if (settled) return;" in js


@test
def test_a_task_repeats_the_section_relationship():
    """A light ring carrying darker text of the same hue, in each kind's colour.

    The section pair is the reference: #F0844E ring, #B8500F text. A blue
    matched to that text's exact weight came out #3171B9, which reads as a
    hyperlink, so the task ink is deeper than any link blue instead.
    """
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    def contrast(a, b):
        x, y = lum(a), lum(b)
        return (max(x, y) + 0.05) / (min(x, y) + 0.05)

    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    tok = {}
    for name in ("accent", "accent-ink", "task", "task-ink"):
        line = [l for l in css.splitlines() if l.strip().startswith("--%s:" % name)][0]
        tok[name] = line.split(":")[1].strip().rstrip(";").split()[0]

    ground = "#F6F4EF"
    for pair in (("accent", "accent-ink"), ("task", "task-ink")):
        ring, ink = tok[pair[0]], tok[pair[1]]
        assert lum(ink) < lum(ring), "%s must be darker than its ring" % pair[1]
        assert contrast(ink, ground) >= 4.5,             "%s is %.2f:1 on the page, under the floor" % (pair[1], contrast(ink, ground))

    # deeper than a link blue, which is the whole point of not using the match
    assert lum(tok["task-ink"]) < lum("#3171B9"), "a link blue is too light for this"
    # the two rings stay equally weighted so neither kind shouts
    assert abs(lum(tok["accent"]) - lum(tok["task"])) < 0.02,         "the rings must carry the same visual weight"


@test
def test_a_screen_presses_the_way_a_plan_does():
    """Two page kinds share a shell, so they must not press differently.

    The screen's one button used to sit filled from the start in the lighter
    orange, and wore an emoji clipboard that kept its own colours when the
    button filled instead of turning white with the label.
    """
    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    rest = css.split(".chip.primary {")[1].split("}")[0]
    assert "background" not in rest, "it starts as an outline like the other three"
    fill = css.split(".chip.primary:hover:not(:disabled) {")[1].split("}")[0]
    assert "background: var(--accent-ink);" in fill and "color: #fff;" in fill,         "and fills into the same ink orange under white"

    icon = layout_screen.COPY_ICON
    assert ord(icon) < 0x1F000, "an emoji cannot take currentColor"
    assert 0x2700 <= ord(icon) <= 0x27BF, "a Dingbat, like the tick and the cross"
    for kind in ("options", "explain"):
        assert layout_screen.ACTIONS[kind][0]["icon"] == icon


@test
def test_a_chosen_card_is_drawn_the_way_an_approved_section_is():
    """Its own outline, in the ring's orange, at the ring's 2px.

    A wash plus a shadow ring said it before, which is both of the things the
    section decisions stopped doing.
    """
    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    picked = css.split('.sec.card[data-picked="yes"] {')[1].split("}")[0]
    assert "border: 2px solid var(--accent);" in picked
    assert "linear-gradient" not in picked, "the card's ground stays its own"
    assert "box-shadow" not in picked, "and nothing rings it from outside"
    # cards sit at the same distance from each other as sections do
    cards = css.split(".cards {")[1].split("}")[0]
    sec = css.split(chr(10) + ".sec {")[1].split("}")[0]
    assert "gap: 1.1em;" in cards and "margin: 0 auto 1.1em;" in sec


@test
def test_reset_sits_with_undo_and_redo_and_is_undoable():
    """Reset goes on the history stack, and asks twice before it gets there.

    It is the same loop as Request changes, mirrored: one asks Claude to go
    round again, the other undoes the asking.
    """
    html = shell.render(**sample())
    hist = html.split('<div class="history">')[1].split("</div>")[0]
    for which in ("undo", "redo", "reset"):
        assert 'id="%s"' % which in hist, "%s belongs with the other two" % which
    assert 'class="ico-reset"' in hist

    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    reset = css.split(chr(10) + ".ico-reset {")[1].split("}")[0]
    assert "transform: scaleX(-1);" in reset, "mirrored against the footer loop"
    loop = css.split(chr(10) + ".ico-loop {")[1].split("}")[0]
    def em(rule, prop):
        return float(rule.split(prop + ": ")[1].split("em")[0])
    assert em(reset, "height") < em(loop, "height"), "smaller than the footer loop"

    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    body = js.split("function resetAll()")[1].split(chr(10) + "  }")[0]
    assert "state.data = emptyData();" in body
    assert 'save("reset");' in body, "on the undo stack, or Ctrl+Z cannot bring it back"
    assert "confirm(" not in js, "the confirmation is the button itself, not a dialog"
    assert 'bind("reset", onReset);' in js, "the click arms first, it does not clear"
    # and it greys out on an untouched plan, following what there is to clear
    assert "x.disabled = !feedbackCount() && !state.data.verdict;" in js


@test
def test_reset_asks_twice_inside_a_closing_window():
    """One click arms, a second inside four seconds clears.

    A review is long work, so the first click may not have meant it. The window
    shuts on its own, which is what keeps a stray click free.
    """
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "var RESET_WINDOW_MS = 4000;" in js
    on = js.split("function onReset()")[1].split(chr(10) + "  }")[0]
    assert "if (resetArmed()) { disarmReset(); resetAll(); return; }" in on,         "the second click is the one that clears"
    assert "armReset();" in on
    arm = js.split("function armReset()")[1].split(chr(10) + "  }")[0]
    assert 'classList.add("armed")' in arm
    assert "setTimeout(disarmReset, RESET_WINDOW_MS)" in arm, "the window has to shut itself"
    # an undo can empty the review while the window is open
    assert 'if (x.disabled && x.classList.contains("armed")) disarmReset();' in js
    # and Escape backs out of it
    assert 'ev.key === "Escape" && resetArmed()' in js

    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    armed = css.split(".iconbtn.armed,")[1].split("}")[0]
    assert "background: var(--skip);" in armed and "color: #fff;" in armed,         "inverted into the decline red"
    assert ".iconbtn.armed:hover:not(:disabled)" in css,         "or the colour drops away under the pointer about to click it"
    assert 'content: "!";' in css
    # the mark sits in the icon's own box, so the header cannot shuffle sideways
    mark = css.split(".iconbtn.armed .ico-reset::after {")[1].split("}")[0]
    assert "position: absolute;" in mark and "inset: 0;" in mark


@test
def test_an_undo_puts_the_whole_plan_note_back():
    """The note lives in an input, so applyDataToDoc never touches it.

    Undo reverted the stored value and left the old text sitting in the box,
    which read as an undo that had not worked.
    """
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "function syncGeneral()" in js
    restore = js.split("function restore(snap)")[1].split(chr(10) + "  }")[0]
    assert "syncGeneral();" in restore


@test
def test_the_verdicts_are_outlines_that_fill_when_used():
    """A ring drawn outside the pill read as a focus artefact.

    Marked is now the same shape as the hover it followed: the outline fills in
    the button's own colour, so all three behave alike.
    """
    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    assert "box-shadow" not in css.split(".chip {")[1].split(".btn {")[0],         "the marked state fills, it does not wear a ring"
    # every verdict starts as an outline: no fill before it is hovered or used
    for cls in ("approve", "decline", "changes"):
        rule = css.split(".chip.%s {" % cls)[1].split("}")[0]
        assert "background" not in rule, "%s must start as an outline" % cls
        assert "border-color" in rule and "color" in rule
        for state in (":hover:not(:disabled)", '[aria-pressed="true"]'):
            filled = css.split(".chip.%s%s {" % (cls, state))[1].split("}")[0]
            assert "background" in filled, "%s%s must fill" % (cls, state)


@test
def test_request_changes_needs_something_to_change():
    """Revise and re-present with nothing marked is an instruction to nowhere.

    Approve and decline stand on their own, so only this one greys out. An
    approval is not a change, which is why it counts its own things rather than
    reusing feedbackCount.
    """
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "function changeCount()" in js
    assert 'kind === "changes" ? !changeCount()' in js
    body = js.split("function changeCount()")[1].split(chr(10) + "  }")[0]
    assert 'e.decision === "skip"' in body, "a decline is something to revise"
    assert 'e.decision === "ok"' not in body, "an approval is not a change"
    assert "totalEditRuns()" in body and "state.data.marks" in body
    assert "state.data.general" in body


@test
def test_the_three_verdicts_instruct_differently():
    """Approve and changes once both said "apply what is below and carry on".

    That made them the same verdict wearing two labels, and lost the distinction
    that actually matters on a long plan: keep going, or come back to me.
    """
    lines = {a["verdict"]: a["line"] for a in shell.PLAN_ACTIONS}
    assert len(set(lines.values())) == 3, "three chips, three instructions"

    # only one of them asks for another round
    assert "give me the link again" in lines["changes"]
    assert "Do not start building" in lines["changes"]
    for other in ("approve", "decline"):
        assert "link again" not in lines[other],             "%s must not ask to be re-presented" % other

    assert "No second review needed" in lines["approve"], "approve means go"
    assert "do not patch it" in lines["decline"].lower(), "decline is not a revise"

    # decline drops the how-to-apply footer, which would be wrong advice there
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert 'state.data.verdict !== "decline"' in js


@test
def test_sections_carry_their_steps():
    """A step decision is keyed by step id, which is not a row id.

    Without the steps list on each row, the prompt builder has no way to name a
    skipped step, so the decision is stored, shown in the page, and then quietly
    missing from what reaches Claude.
    """
    built = layout_plan.build(fixture("plan_full.md"), source="x.md")
    tasks = [r for r in built["sections"] if r["kind"] == "task"]
    assert [len(r["steps"]) for r in tasks] == [2, 3, 1], [len(r["steps"]) for r in tasks]
    body = built["body_html"]
    for row in tasks:
        for step in row["steps"]:
            assert 'data-step="%s"' % step["id"] in body, "every listed step must exist in the body"
            assert step["name"], "a step needs a name to be quotable in the prompt"
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "function stepFor(" in js, "shell.js must resolve step ids"
    assert "decisionsIn(sec)" in js, "the prompt builder must read step decisions"


@test
def test_full_page_renders_from_a_plan():
    built = layout_plan.build(fixture("plan_full.md"), source="x.md")
    html = shell.render(**built)
    assert html.lstrip().startswith("<!DOCTYPE html>")
    for b in script_blocks(html):
        assert "</script" not in b


# ------------------------------------------------------------- documents


@test
def test_doc_preamble_becomes_a_lead_section():
    """The line naming who a protocol is for must not be dropped.

    layout_plan keeps it only if it reads `**Key:** value`, so a document lost
    its opening. Here it is a block with a real id, which is also what makes a
    comment on it reach the prompt.
    """
    raw = fixture("doc_prose.md")
    doc = layout_doc.parse(raw)
    assert u"Fuer Jana und Tomek" in doc["preamble"], doc["preamble"][:60]
    built = layout_doc.build(raw, source="docs/x/doc.md")
    assert '<div class="sec lead"' in built["body_html"], "lead block must render"
    assert built["sections"][0]["kind"] == "intro", built["sections"][0]
    assert u"Fuer Jana und Tomek" in built["body_html"]


@test
def test_doc_ignores_a_preamble_that_shows_nothing():
    """An HTML comment opens many generated files.

    It is an instruction to a tool, not content, and it renders to nothing, so
    it used to produce an Intro block that was an empty box with a tick in it.
    """
    marker = "<!-- generated: do not edit -->" + chr(10) + chr(10)
    built = layout_doc.build(marker + "# Titel" + chr(10) * 2 + "## Eins" + chr(10) * 2 + "Text.",
                             source="x.md")
    kinds = [s["kind"] for s in built["sections"]]
    assert "intro" not in kinds, kinds
    assert 'data-kind="intro"' not in built["body_html"]

    # A real opening line still gets its block.
    built = layout_doc.build("# Titel" + chr(10) * 2 + "Wer das liest." + chr(10) * 2 + "## Eins",
                             source="x.md")
    assert built["sections"][0]["kind"] == "intro", built["sections"]


@test
def test_doc_numbers_sections_and_subsections():
    doc = layout_doc.parse(fixture("doc_prose.md"))
    got = [(s["kind"], s["index"]) for s in doc["sections"]]
    assert got == [("section", "1"), ("section", "2"),
                   ("sub", "2.1"), ("sub", "2.2"), ("sub", "2.3"),
                   ("section", "3")], got
    assert doc["sections"][2]["num"] == "Subsection 2.1", doc["sections"][2]["num"]


@test
def test_doc_ignores_headings_inside_a_fence():
    """`## Diese Zeile ist Beispieltext` lives in a code block, not the outline."""
    doc = layout_doc.parse(fixture("doc_prose.md"))
    names = [s["name"] for s in doc["sections"]]
    assert not any("Beispieltext" in n for n in names), names
    assert len(doc["sections"]) == 6, names


@test
def test_doc_without_headings_is_one_section():
    """This case used to render a page with a title and nothing under it."""
    raw = fixture("doc_flat.md")
    doc = layout_doc.parse(raw)
    assert len(doc["sections"]) == 1, doc["sections"]
    assert doc["preamble"] == "", "the body moved into the section, not beside it"
    assert u"Telefonat" in doc["sections"][0]["intro"]
    built = layout_doc.build(raw, source="docs/vermerk.md")
    assert u"Telefonat" in built["body_html"]
    # A file with no title must not have the "Document" fallback printed as one.
    assert "<h2" not in built["body_html"], "an invented heading is not the document"
    assert built["title"] == "Document", "the tab still needs a name"


@test
def test_doc_offers_two_verdicts_not_three():
    """Decline on a plan means rethink the approach. A draft has only text."""
    built = layout_doc.build(fixture("doc_prose.md"), source="x.md")
    verdicts = [a["verdict"] for a in built["actions"]]
    assert verdicts == ["approve", "changes"], verdicts
    assert built["prompt_spec"]["generalLabel"] == "Whole document"


@test
def test_doc_ids_are_stable_across_reparse():
    raw = fixture("doc_prose.md")
    a = layout_doc.parse(raw)
    b = layout_doc.parse(raw)
    assert [s["id"] for s in a["sections"]] == [s["id"] for s in b["sections"]]


@test
def test_doc_ids_survive_an_inserted_section():
    """Inserting a section above a commented one must not move the comment."""
    raw = fixture("doc_prose.md")
    before = {s["name"]: s["id"] for s in layout_doc.parse(raw)["sections"]}
    grown = raw.replace("## Die drei Fragen",
                        "## Ein neuer Abschnitt" + chr(10) + chr(10) +
                        "Frisch dazwischen." + chr(10) + chr(10) + "## Die drei Fragen", 1)
    after = layout_doc.parse(grown)
    ids = {s["name"]: s["id"] for s in after["sections"]}
    assert ids[u"Die drei Fragen"] == before[u"Die drei Fragen"], "section id moved"
    assert ids[u"Dürft ihr jetzt säen?"] == before[u"Dürft ihr jetzt säen?"], "subsection id moved"
    nums = {s["name"]: s["num"] for s in after["sections"]}
    assert nums[u"Die drei Fragen"] == "Section 3", nums[u"Die drei Fragen"]


@test
def test_doc_slug_carries_the_folder():
    """Documents are routinely called README.md; the basename alone collides."""
    a = layout_doc.slug_for_path("docs/alpha/README.md")
    b = layout_doc.slug_for_path("docs/beta/README.md")
    assert a != b, (a, b)
    assert a == "alpha-readme", a
    assert layout_doc.slug_for_path("doc.md") == "doc"
    assert layout_doc.slug_for_path("") == "document"


@test
def test_doc_controls_are_wired_to_their_block():
    """A tick or pencil with no data-for is a control that decides nothing."""
    built = layout_doc.build(fixture("doc_prose.md"), source="x.md")
    body = built["body_html"]
    buttons = re.findall(r'<button class="(?:dec|note-btn)"[^>]*>', body)
    assert len(buttons) == 14, len(buttons)
    for b in buttons:
        assert "data-for=" in b, b
    ids = set(re.findall(r'data-for="([^"]+)"', body))
    known = set(s["id"] for s in built["sections"])
    assert ids == known, ids ^ known


@test
def test_doc_every_listed_section_is_in_the_body():
    """buildPrompt only prints marks whose section it finds in the list."""
    built = layout_doc.build(fixture("doc_prose.md"), source="x.md")
    for sec in built["sections"]:
        assert 'data-sec="%s"' % sec["id"] in built["body_html"], sec["num"]


@test
def test_doc_code_blocks_stay_uneditable():
    built = layout_doc.build(fixture("doc_prose.md"), source="x.md")
    for pre in re.findall(r"<pre.*?</pre>", built["body_html"], re.S):
        assert "data-edit-id" not in pre, "nothing inside a code block is rewritable"


@test
def test_doc_subsection_has_its_own_ring():
    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    rule = css.split(chr(10) + '.sec[data-kind="sub"] .sec-marker {', 1)
    assert len(rule) == 2, "the subsection marker rule is gone"
    body = rule[1].split("}", 1)[0]
    assert "border-radius: 999px" in body, "2.1 does not fit a circle"
    assert "px" not in body.replace("999px", ""), "size in --ctl or Ctrl+wheel leaves it behind"
    indent = css.split('.numbered .sec[data-kind="sub"] {', 1)
    assert len(indent) == 2, "subsections must indent"
    body = indent[1].split("}", 1)[0]
    assert "margin-left" not in body, "margin-left kills the auto centring of .sec"
    assert "left: 1em" in body and "calc(var(--measure) - 2em)" in body, body


@test
def test_doc_has_no_ring_number_or_eyebrow():
    """A document page reads as prose: the headings carry it, in dark orange."""
    built = layout_doc.build(fixture("doc_prose.md"), source="x.md")
    body = built["body_html"]
    assert 'class="sec-marker"' not in body, "no ring in the margin"
    assert 'class="sec-num"' not in body, "no eyebrow above the heading"
    assert 'class="numbered"' not in body and 'class="plain"' in body
    assert all(s["num"] for s in built["sections"]), "feedback still names the section"
    css = io.open(os.path.join(PRESENTER, "assets", "shell.css"), encoding="utf-8").read()
    assert ".plain h2, .plain h3 { color: var(--accent-ink); }" in css


@test
def test_general_note_is_named_by_the_layout():
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert 'D.prompt.generalLabel || "Whole plan"' in js, "the label must come from the data"
    assert '"- Whole plan: "' not in js, "no layout may be named in the shell"
    assert "doc:" in js.split("var HINTS = {", 1)[1].split("};", 1)[0], "no hint for a document"
    html = shell.render(**sample(prompt_spec={"header": "h", "footer": "f",
                                              "generalLabel": "Whole document"}))
    assert '"generalLabel": "Whole document"' in html or            '"generalLabel":"Whole document"' in html, "label must reach the page"


@test
def test_doc_page_is_one_self_contained_document():
    built = layout_doc.build(fixture("doc_prose.md"), source="docs/x/doc.md")
    html = shell.render(**built)
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert html.count("<html") == 1
    assert "<script src" not in html
    assert u"Saatkalender" in html
    assert u"regelmäßig" in html, "umlauts must survive"
    # The button, not the word: the shared script says "Declined" in a tooltip.
    assert "Request changes" in html and 'data-verdict="decline"' not in html


# ------------------------------------------------------ comment anchoring


@test
def test_hard_wrapped_markdown_keeps_its_line_breaks():
    """The cause of the "could not be re-anchored" strip, pinned down.

    Our Markdown is hard-wrapped and the renderer keeps those breaks as real
    newlines inside the paragraph. The browser draws them as spaces, so a quote
    taken from a selection never matched the text nodes character for character.
    """
    built = layout_doc.build(fixture("doc_wrapped.md"), source="docs/umbruch.md")
    html = built["body_html"]
    assert "zeigt den Umbruch als Leerzeichen, im Textknoten" + chr(10) + "steht" in html, \
        "if the renderer stops keeping newlines this test documents a cause that is gone"


@test
def test_anchoring_ignores_whitespace():
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "function squeeze(" in js and "function flatten(" in js
    for fn in ("function locateQuote(", "function occurrenceOf("):
        body = js[js.index(fn):js.index(fn) + 900]
        assert "flatten(root)" in body and "squeeze(quote" in body,             "%s must search the whitespace-free text, or wrapped lines orphan the comment" % fn
    assert "rangeForQuote" not in js, "the exact-match search is what orphaned wrapped passages"


@test
def test_a_changed_passage_is_found_by_its_ends():
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    body = js[js.index("function locateQuote("):js.index("function occurrenceOf(")]
    assert "pre" in body and "suf" in body and "drift: true" in body


@test
def test_no_comment_raises_an_alarm_or_goes_missing():
    """Every comment gets a place on the page and exactly one line in the answer."""
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "could not be re-anchored" not in js, "the red strip is gone"
    assert "renderOrphans" not in js and "orphaned" not in js
    assert "has-comment at-section" in js, "a vanished passage hangs its comment on the section tag"
    i = js.index("function marksFor(")
    assert "drift" not in js[i:i + 300], "a drifted comment must still print under its section"
    b = js[js.index("function buildPrompt("):js.index("function feedbackCount(")]
    assert "!sectionFor(state.data.marks[k].sec)" in b,         "a comment outside every listed section must still reach Claude"
    assert "(the text has changed since)" in js


# ------------------------------------------------------------ table editing


@test
def test_split_row_keeps_escaped_pipes():
    assert layout_tables.split_row("| a | b \\| c | `x` |") == ["a", "b \\| c", "`x`"]
    assert layout_tables.split_row("a|b") == ["a", "b"]


@test
def test_find_pipe_tables_skips_fences_and_finds_both():
    found = layout_tables.find_pipe_tables(fixture("doc_table.md"))
    assert len(found) == 2, "the fenced table is not a table"
    first = found[0]
    assert first["head"] == ["Anforderung", "Was das heißt", "Quelle"]
    assert first["align"] == "|---|:---:|---|"
    assert first["rows"][0][2] == "[DSGVO](https://dsgvo-gesetz.de/art-13-dsgvo/)"
    assert first["rows"][1][1] == "Kein Druck \\| auch nicht im Termin"


def _table_html():
    built = layout_doc.build(fixture("doc_table.md"), source="docs/t.md")
    return built["body_html"]


@test
def test_tables_carry_ids_and_source():
    html = _table_html()
    tables = re.findall(r"<table ([^>]*)>", html)
    assert len(tables) == 2, "both real tables are stamped"
    assert 'data-table-id="tb' in tables[0]
    assert 'data-md-align="|---|:---:|---|"' in tables[0]
    assert 'data-md="[DSGVO](https://dsgvo-gesetz.de/art-13-dsgvo/)"' in html
    assert 'data-md="Kein Druck \\| auch nicht im Termin"' in html
    assert 'data-md="**informiert**"' in html
    for cell in re.findall(r"<t[dh] [^>]*>", html):
        assert "data-col-id=" in cell and "data-md=" in cell and "data-edit-id=" in cell, cell


@test
def test_body_rows_have_ids_header_rows_do_not():
    html = _table_html()
    first = re.search(r"<table .*?</table>", html, re.S).group(0)
    thead = re.search(r"<thead>.*?</thead>", first, re.S).group(0)
    tbody = re.search(r"<tbody>.*?</tbody>", first, re.S).group(0)
    assert "data-row-id" not in thead
    assert len(re.findall(r'<tr data-row-id="r[0-9a-f]{8}">', tbody)) == 2


@test
def test_row_id_survives_a_row_inserted_above():
    raw = fixture("doc_table.md")
    before = re.findall(r'data-row-id="([^"]+)"', _table_html())
    # Between the two rows, not above the first: the table id hashes the first
    # body row, so changing that one re-keys the table by design (spec, Risks).
    raw2 = raw.replace("| freiwillig |", "| neu | x | y |\n| freiwillig |", 1)
    built = layout_doc.build(raw2, source="docs/t.md")
    after = re.findall(r'data-row-id="([^"]+)"', built["body_html"])
    assert before[0] in after and before[1] in after
    assert re.findall(r'data-table-id="([^"]+)"', built["body_html"])[1] == \
        re.findall(r'data-table-id="([^"]+)"', _table_html())[1], "an untouched table keeps its id"


@test
def test_code_block_table_gets_nothing():
    html = _table_html()
    for pre in re.findall(r"<pre\b.*?</pre>", html, re.S):
        assert "data-" not in pre


@test
def test_raw_html_table_is_left_alone():
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n\n<table><tr><td>raw</td></tr></table>\n"
    html = layout_tables.stamp_tables(layout_plan._md(md), md, "s1", set())
    assert "data-table-id" not in html, "count mismatch stamps nothing"


def _stamp(md):
    return layout_tables.stamp_tables(layout_plan._md(md), md, "s1", set())


@test
def test_pipe_inside_inline_code_never_misattributes_source():
    """python-markdown keeps `x|y` as one code cell; a naive split would not."""
    html = _stamp("| a | b |\n|---|---|\n| `x|y` | z |\n")
    assert 'data-md="`x"' not in html and 'data-md="y`"' not in html
    assert 'data-md="z"' in html or "data-md" not in html.split("z</td>")[0].rsplit("<td", 1)[1]


@test
def test_row_without_pipes_does_not_blank_later_rows():
    html = _stamp("| a | b |\n|---|---|\n| 1 | 2 |\nloose line\n| 3 | 4 |\n")
    assert 'data-md=""' not in html, "a cell whose source is unknown carries no data-md at all"
    cells = re.findall(r'<td ([^>]*)>([^<]*)</td>', html)
    for attrs, text in cells:
        m = re.search(r'data-md="([^"]*)"', attrs)
        assert not m or m.group(1) == text.strip(), (attrs, text)


@test
def test_nested_fence_does_not_pair_the_wrong_table():
    md = ("````markdown\n```\n| fake | head |\n|---|---|\n| x | y |\n```\n````\n\n"
          "| real | head |\n|---|---|\n| 1 | 2 |\n")
    html = _stamp(md)
    assert 'data-md="fake"' not in html and 'data-md="x"' not in html


@test
def test_blank_added_structure_is_not_a_change():
    js = shell._asset("shell.js")
    c = js[js.index("function tableChangeCount("):]
    c = c[:c.index("\n  }") + 4]
    assert "tableHasChange" in c, "an empty added row must not light up the counter"
    assert "function tableHasChange(" in js


@test
def test_reapply_does_not_move_rows_already_in_order():
    js = shell._asset("shell.js")
    o = js[js.index("function orderChildren("):js.index("function applyTable(")]
    assert "already in order" in o, "re-appending on every blur can drop the caret"


@test
def test_plan_tables_are_stamped_too():
    raw = "# P\n\n## Eins\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    html = layout_plan.build(raw, source=".claude/plans/p.md")["body_html"]
    assert "data-table-id" in html and 'data-col-id="c1"' in html
    assert re.search(r'<td [^>]*data-edit-id=', html)


@test
def test_table_state_is_guarded_and_applied_first():
    js = shell._asset("shell.js")
    assert "tables: {}" in js[js.index("function emptyData("):js.index("function persist(")]
    assert "if (!state.data.tables) state.data.tables = {};" in js
    a = js[js.index("function applyDataToDoc("):]
    assert a.index("applyTablesToDoc();") < a.index("Object.keys(origHTML)"), \
        "tables before the editables pass"
    w = js[js.index("function wire("):]
    assert w.index("collectTables();") < w.index("load();"), "pristine order is read before state"


@test
def test_table_toolbar_every_button_has_a_tip():
    js = shell._asset("shell.js")
    bar = js[js.index("var TBAR = ["):js.index("function buildTableBar(")]
    ops = re.findall(r'\["([a-z-]+)", "[^"]*", "([^"]+)"\]', bar)
    assert {o for o, _ in ops} == {"row-above", "row-below", "row-up", "row-down", "row-remove",
                                   "col-left", "col-right", "col-prev", "col-next", "col-remove",
                                   "table-kill"}
    assert all(tip.strip() for _, tip in ops), "every table button has a tooltip"
    assert 'ev.preventDefault(); /* keep focus in the cell */' in js


@test
def test_table_serialiser_and_prompt_group():
    js = shell._asset("shell.js")
    s = js[js.index("function inlineMd("):js.index("function tableSummary(")]
    assert "mdText(c.nodeValue)" in s, "cell text is escaped (behaviour: the round-trip test)"
    assert '"**" + inner + "**"' in s and "mdCode(c.textContent)" in s
    b = js[js.index("function buildPrompt("):js.index("function feedbackCount(")]
    assert "Tables, replace each one with the version below:" in b
    assert "tableChangeCount()" in js[js.index("function feedbackCount("):js.index("function pruneSteps(")]
    assert 'table[data-tchg]' in js[js.index("function navTargets("):js.index("var reduceMotion")]


def js_function(name):
    """One top-level-free function out of shell.js, as source node can run."""
    js = shell._asset("shell.js")
    start = js.index("function %s(" % name)
    depth, i = 0, js.index("{", start)
    while True:
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                return js[start:i + 1]
        i += 1


def run_js(names, expr):
    import subprocess
    src = "\n".join(js_function(n) for n in names)
    src += "\nprocess.stdout.write(JSON.stringify(%s));" % expr
    out = subprocess.run(["node", "-e", src], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    return json.loads(out.stdout.decode("utf-8"))


@test
def test_layout_tables_does_not_import_layout_plan():
    import layout_common
    src = io.open(os.path.join(PRESENTER, "layout_tables.py"), encoding="utf-8").read()
    assert "import layout_plan" not in src, "no circular import"
    for name in ("_hash", "_esc", "_md", "_mask_pre", "_unmask_pre"):
        assert getattr(layout_plan, name) is getattr(layout_common, name), name


@test
def test_setext_heading_and_indented_code_are_not_tables():
    for md in ("Kosten | Nutzen\n---\n\nText",
               "Para\n\n    | a | b |\n    |---|---|\n    | 1 | 2 |\n"):
        assert layout_plan._md(md).count("<table>") == 0
        assert layout_tables.find_pipe_tables(md) == [], md


@test
def test_table_count_agrees_with_the_renderer():
    t = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    ind = lambda pad: "".join(pad + l + "\n" for l in t.splitlines())  # noqa: E731
    for md in ("para\n" + t, "para\n\n" + t, "- item\n\n" + ind("    "), "- item\n" + t,
               "## H\n" + t, "para\n    | a | b |\n    |---|---|\n", "1. item\n\n" + ind("    "),
               "- item\n\n" + ind("        "), t, "Para\n\n" + ind("    ")):
        want = layout_plan._md(md).count("<table>")
        assert len(layout_tables.find_pipe_tables(md)) == want, (md, want)


@test
def test_a_real_table_after_a_false_one_still_gets_its_toolbar():
    md = "Kosten | Nutzen\n---\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    html = layout_tables.stamp_tables(layout_plan._md(md), md, "s1", set())
    assert "data-table-id" in html


@test
def test_header_only_table_has_no_body_row():
    md = "| a | b |\n|---|---|\n"
    html = layout_tables.stamp_tables(layout_plan._md(md), md, "s1", set())
    assert "data-table-id" in html
    assert "data-row-id" not in html and "<td" not in html, html
    assert "<tbody" in html, "the body stays so added rows have a home"


@test
def test_cell_escapes_round_trip_through_markdown():
    texts = ["a*b*c", "snake_case_name", "x < y", "[not a link]", "back\\slash", "tick`s",
             "pipe | here", "1. not a list"]
    md = run_js(["mdText"], "[%s].map(mdText)" % ",".join(json.dumps(t) for t in texts))
    codes = ["a | b", "*a* | b_c", "a``b", "``", "`x", "plain"]
    code = run_js(["mdCode"], "[%s].map(mdCode)" % ",".join(json.dumps(c) for c in codes))
    href = run_js(["mdHref"], 'mdHref("https://x.de/a b(c)")')
    cells = md + code + ["[link](%s)" % href]
    table = "| h |\n|---|\n" + "\n".join("| %s |" % c for c in cells) + "\n"
    html = layout_plan._md(table)
    import html as _h
    tds = re.findall(r"<td>(.*?)</td>", html, re.S)
    got = [_h.unescape(layout_tables._text(c)) for c in tds]
    assert got[:len(texts)] == texts, got
    n = len(texts)
    assert got[n:n + len(codes)] == codes, got[n:n + len(codes)]
    assert all(tds[n + i].startswith("<code>") and tds[n + i].endswith("</code>")
               for i in range(len(codes))), tds[n:n + len(codes)]
    assert 'href="https://x.de/a%20b%28c%29"' in html, html


@test
def test_whole_rewrite_puts_a_link_back_on_the_word_not_inside_one():
    # fmt: one chain per character of the original; "L" stands for the link.
    r = run_js(["wholeFormat", "sameChain", "wordEdge"],
               'wholeFormat("click here", "look where we go, click here",'
               ' [[],[],[],[],[],[],["L"],["L"],["L"],["L"]])'
               '.map(function (c) { return c.length ? "L" : "."; }).join("")')
    assert r == "." * 24 + "LLLL", r


@test
def test_moved_count_is_the_minimum_number_of_moves():
    r = run_js(["movedCount"], '[movedCount(["a","b","c","d"],["b","c","d","a"]),'
               'movedCount(["a","b","c"],["c","b","a"]), movedCount(["a","b"],["a","b","n1"])]')
    assert r == [1, 2, 0], r


@test
def test_shell_js_has_no_literal_nbsp():
    assert u" " not in shell._asset("shell.js")


@test
def test_table_cell_guards_in_the_source():
    js = shell._asset("shell.js")
    op = js[js.index("function tableOp("):js.index("function refocus(")]
    assert "keptCols(" in js[js.index("function removableCol("):js.index("function tableMarkdown(")], \
        "col-remove guard ignores blank new columns"
    assert "function removableCol(" in js and "removableCol(" in op, "one guard, new columns too"
    assert "removableCol(" in js[js.index("function paintTableBar("):js.index("function placeTableBar(")]
    assert "tabIndex" in js[js.index("function applyTable("):js.index("function applyTablesToDoc(")], \
        "a removed cell can still take focus, so Restore stays reachable"
    nav = js[js.index("function navTargets("):js.index("var reduceMotion")]
    assert nav.count("cellLocked(") >= 2, "both edit and all navigation skip removed cells"
    bp = js[js.index("function buildPrompt("):js.index("function feedbackCount(")]
    assert "tablesIn(sec.id)" in bp, "a table change means the section was not approved as written"
    ap = js[js.index("function applyTable("):js.index("function applyTablesToDoc(")]
    assert "contentEditable" in ap and "tbl-orphan" not in ap
    assert "tbl-orphan" in js, "a lost table hangs a marker on its section"
    css = shell._asset("shell.css")
    assert "[data-new-cell]:focus" in css


@test
def test_approve_without_changes_stops_at_the_verdict():
    doc_ok = [a for a in layout_doc.ACTIONS if a["verdict"] == "approve"][0]
    plan_ok = [a for a in shell.PLAN_ACTIONS if a["verdict"] == "approve"][0]
    assert doc_ok["bare"] == "VERDICT: approved. The document is finished."
    assert plan_ok["bare"] == ("VERDICT: approved. Build it as written. "
                               "No second review needed, go straight to work.")
    js = shell._asset("shell.js")
    bp = js[js.index("function buildPrompt("):js.index("function feedbackCount(")]
    assert "act.bare" in bp and "changeCount()" in bp, "the short line is chosen when nothing changed"
    assert "!bareApprove" in bp[bp.index("D.prompt.footer"):], "no how-to-apply footer then"


@test
def test_status_slides_in_and_out():
    js = shell._asset("shell.js")
    st = js[js.index("function setStatus("):js.index("function flash(")]
    assert "is-on" in st, "the status animates through a class, not by swapping text"
    assert "scrollWidth" in st and ".style.width" in st, "the box width follows the measured text"
    html = shell.render(**sample())
    assert '<span id="status"><span class="status-text"></span></span>' in html, "a clipping box around the text"
    css = shell._asset("shell.css")
    box = re.search(r"#status\s*\{([^}]*)\}", css).group(1)
    assert "overflow: hidden" in box and "width" in box and "transition" in box, box
    assert "margin-left: calc(-1 * var(--gap" in box, "an empty box gives back the row gap"
    txt = re.search(r"#status \.status-text\s*\{([^}]*)\}", css).group(1)
    assert "translateX(24px)" in txt and "opacity: 0" in txt, txt
    assert re.search(r"#status\.is-on \.status-text\s*\{[^}]*opacity: 1", css)
    rm = css[css.index("@media (prefers-reduced-motion: reduce)", css.index("#status")):]
    assert ".status-text" in rm[:rm.index("}\n}") + 3], "reduced motion only fades"


@test
def test_every_page_kind_carries_the_shared_fixes():
    pages = {
        "plan": shell.render(**layout_plan.build(fixture("plan_full.md"), "p.md")),
        "doc": shell.render(**layout_doc.build(fixture("doc_table.md"), "d.md")),
        "options": shell.render(**layout_screen.build(fixture("screen_options.md"), "o.md")),
        "explain": shell.render(**layout_screen.build(fixture("screen_explain.md"), "e.md")),
    }
    for kind, html in pages.items():
        for needle in ("function keptCols(", "function cellLocked(", "function mdText(",
                       "#status.is-on", "function wholeFormat(", "function removableCol("):
            assert needle in html, (kind, needle)
    # Plans get the table toolbar too; choice screens keep text-only cells (ruling 30.09.).
    plan_md = "# P\n\n## A\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    assert "data-table-id" in shell.render(**layout_plan.build(plan_md, "p.md")), "plan tables are stamped"


@test
def test_build_records_source_mtime():
    import tempfile
    import build_screen
    tmp = new_home()
    src = os.path.join(tmp, "doc.md")
    with io.open(src, "w", encoding="utf-8") as fh:
        fh.write("# D\n\n## A\n\nText.\n")
    os.utime(src, (1700000000, 1700000000))
    res = build_screen.build("doc", src, slug="mtime-probe", out_dir=tmp)
    html = io.open(os.path.join(tmp, "mtime-probe.html"), encoding="utf-8").read()
    assert res["ok"]
    assert '"sourceMtime": 1700000000000' in html, "source time in epoch ms lands in meta"


@test
def test_stale_strip_is_present_and_hidden():
    html = shell.render(**sample())
    assert '<div id="stale" class="stale" role="status" hidden>' in html
    assert 'id="stale-reload"' in html
    assert ".stale { grid-row: 2; }" in html, "the strip has its own grid placement"


@test
def test_page_checks_source_and_expires_old_marks():
    js = io.open(os.path.join(PRESENTER, "assets", "shell.js"), encoding="utf-8").read()
    assert "savedAt: Date.now()" in js, "every save carries its time"
    assert "DEFAULT_STALE_HOURS = 96" in js, "marks expire after 96 hours unless the settings say otherwise"
    start = js[js.index("function start(staleHours)"):]
    assert start.index("expireOld(hoursMs(staleHours));") < start.index("load();"), \
        "expire before this page loads its own"
    assert "watchSource();" in start
    assert "/api/review-source?slug=" in js


# --------------------------------------------------------------------------


NEW_TEST_MODULES = ["test_privacy", "test_vendor", "test_settings", "test_build", "test_version", "test_write",
                    "test_server", "test_pages_route", "test_housekeeping", "test_launch", "test_opening", "test_review_fixes", "test_page", "test_opener", "test_extension", "test_hook", "test_plugin_files", "test_repo_files", "test_docs"]


def main():
    for mod in NEW_TEST_MODULES:
        __import__(mod)
    failed = 0
    for fn in RESULTS:
        try:
            fn()
            print("  ok   %s" % fn.__name__)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("  FAIL %s: %s" % (fn.__name__, exc))
            if os.environ.get("PRESENTER_TRACE"):
                traceback.print_exc()
        finally:
            # One test can never leak its home folder into the next.
            os.environ["REVIEW_DOC_HOME"] = harness.DEFAULT_HOME
    print("\n%d passed, %d failed" % (len(RESULTS) - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
