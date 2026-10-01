# -*- coding: utf-8 -*-
"""What Phase 3 adds to the page: the credit line, mark expiry from the settings, and
the settings panel.

There is no JavaScript runtime in this suite, so like the ported page tests these pin
the source. The browser check in the Phase 3 plan covers what they cannot.
"""
import html as htmllib
import io
import json
import os
import re

from harness import test, HERE

import shell
import layout_doc

PLUGIN = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(PLUGIN))


def page(version="9.8.7"):
    built = layout_doc.build("# T\n\n## A\n\nSome text here.\n", source="/x/t.md")
    if version:
        built["meta"]["version"] = version
    return shell.render(**built)


def credit(html):
    i = html.index('<div class="credit"')
    return html[i:html.index("</main>", i)]


def js():
    return shell._asset("shell.js")


def css():
    return shell._asset("shell.css")


def fn_body(src, name):
    """The text of one top-level function in shell.js, up to the next one."""
    i = src.find("\n  function " + name + "(")
    i = i + 1 if i >= 0 else src.index("function " + name + "(")
    j = src.find("\n  function ", i + 1)
    return src[i:j if j > 0 else len(src)]


@test
def test_credit_line_closes_the_document():
    html = page()
    start, end = html.index('<div id="doc">'), html.index("</main>")
    at = html.index('<div class="credit"')
    assert start < at < end, "inside #doc"
    assert html.rfind("data-sec=", 0, end) < at, "after the last section"
    c = credit(html)
    text = htmllib.unescape(re.sub(r"<[^>]+>", "", c))
    for part in ("/review-doc skills v.9.8.7 by Filip Muszyński", "MIT License", "GitHub", "Settings"):
        assert part in text, part
    assert "Muszynski" not in text, "the name is spelled with ń"
    assert 'href="https://github.com/filmuszynski"' not in c, "the name is plain text, not a link"
    assert "/review-doc skills by Filip Muszyński" in htmllib.unescape(
        re.sub(r"<[^>]+>", "", credit(page(version=None)))), "no version, no 'v.'"
    assert 'href="%s"' % shell.LICENSE_URL in c and 'href="%s"' % shell.REPO_URL in c
    assert 'id="open-settings"' in c
    assert "—" not in c
    assert "credit-version" not in credit(page(version=None)), "no version, no 'v'"


@test
def test_credit_links_match_plugin_json():
    with io.open(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    assert shell.REPO_URL == manifest["homepage"]
    assert shell.LICENSE_URL == shell.REPO_URL + "/blob/main/LICENSE"
    assert os.path.isfile(os.path.join(REPO, "LICENSE"))


@test
def test_credit_line_is_not_reviewable():
    c = credit(page())
    assert "data-edit-id" not in c and "data-sec" not in c and "note-btn" not in c
    rule = css().split("#doc .credit {", 1)[1].split("}", 1)[0]
    assert "user-select: none" in rule
    up = js().split('docEl.addEventListener("mouseup"', 1)[1][:900]
    assert ".credit" in up, "a selection touching the credit line never asks for a comment"


@test
def test_credit_hides_settings_in_print():
    printed = css().split("@media print {", 1)[1].split("\n}", 1)[0]
    hidden = [l.split("{")[0] for l in printed.splitlines() if "display: none" in l][0]
    assert ".credit-tail" in hidden, "the settings button is hidden in print"
    assert not re.search(r"\.credit(?![-\w])", hidden), "the line itself stays"


@test
def test_finish_overlay_never_prints():
    printed = css().split("@media print {", 1)[1].split("\n}", 1)[0]
    hidden = [l.split("{")[0] for l in printed.splitlines() if "display: none" in l][0]
    assert re.search(r"\.finish(?![-\w])", hidden), "the finish overlay is hidden in print"


@test
def test_refused_close_message_cannot_fire_after_cancel():
    onc = fn_body(js(), "onFinishClose")
    cb = onc[onc.index("setTimeout(function () {"):]
    assert cb.split("\n")[1].strip() == "if (!finishKind) return;", cb


@test
def test_mark_expiry_follows_the_stale_hours_setting():
    src = js()
    assert "EXPIRE_MS = 96" not in src, "no fixed window any more"
    assert "DEFAULT_STALE_HOURS = 96" in src, "the fallback with no server"
    fetcher = fn_body(src, "fetchSettings")
    assert 'fetch("/api/settings"' in fetcher and "Promise.race" in fetcher, "bounded wait"
    assert ".catch(function () { return null; })" in fetcher, "never rejects"
    wire = fn_body(src, "wire")
    assert "fetchSettings().then(" in wire
    assert "start(s ? s.stale_hours : cachedStaleHours())" in wire
    start = fn_body(src, "start")
    assert start.index("expireOld(hoursMs(staleHours))") < start.index("load();"), \
        "expire before loading, and only once the setting is known"
    expire = fn_body(src, "expireOld")
    assert "function expireOld(maxAgeMs, keep)" in expire and "k === keep" in expire


@test
def test_page_comments_name_the_server_not_the_ring():
    """The ring was the author's private dashboard; the plugin has its own server."""
    assert not re.search(r"\b(the|no) ring\b", js(), re.I), \
        "comments still point at the ring"


@test
def test_settings_panel_posts_json_and_confirms():
    src = js()
    post = fn_body(src, "postSettings")
    assert 'fetch("/api/settings"' in post and 'method: "POST"' in post
    assert '"Content-Type": "application/json"' in post and "JSON.stringify(update)" in post
    panel = fn_body(src, "openSettings")
    assert 'flash("Settings saved")' in panel
    assert "rememberSettings(res.settings)" in panel
    assert "expireOld(hoursMs(res.settings.stale_hours), LSKEY)" in panel, "never the open page's marks"
    assert 'res.field === "stale_hours"' in panel, "a refused number is shown on its field"
    assert "did not answer" in fn_body(src, "wireSettings"), "a stopped server says so"


@test
def test_settings_panel_warns_before_deleting_this_page():
    panel = fn_body(js(), "openSettings")
    assert ('"This page is " + Math.floor(age) + " hours old and would be deleted at the next cleanup."'
            in panel)
    assert '"Save anyway"' in panel
    assert "age > h" in panel
    assert "Date.parse(D.meta.generatedAt" in fn_body(js(), "pageAgeHours")


@test
def test_settings_panel_skips_html_until_v1_1():
    src = js()
    rows = src.split("var KIND_ROWS = [", 1)[1].split("];", 1)[0]
    for key in ("md", "html", "plan", "choice"):
        assert 'key: "%s"' % key in rows, key
    assert re.search(r'key: "html"[^}]*note: "arrives in 1\.2"[^}]*off: true', rows)
    assert "if (!k.off) update.kinds[k.key]" in fn_body(src, "openSettings"), "html is never sent"
    assert "vscode_asked" not in fn_body(src, "openSettings")


@test
def test_settings_button_is_disabled_from_file():
    w = fn_body(js(), "wireSettings")
    assert "if (!onServer())" in w
    assert 'setAttribute("aria-disabled", "true")' in w
    assert "Settings need the local review server" in w and "/review-doc:settings" in w
    assert '.credit-settings[aria-disabled="true"]' in css()


@test
def test_settings_panel_closes_like_a_bubble():
    src = js()
    assert "openBubble(btn.getBoundingClientRect()" in fn_body(src, "openSettings")
    i = src.index("if (bubble && !bubble.contains(ev.target)) closeBubble();")
    assert "#open-settings" in src[i - 400:i], "the button toggles; outside click does not reopen it"
    assert "wireSettings();" in fn_body(src, "start")
    rule = css().split(".settings-panel {", 1)[1].split("}", 1)[0]
    assert "width" in rule


@test
def test_credit_line_sits_on_the_text_column():
    """Its em is 0.8 of the document's, so the section measure and side padding are
    divided by 0.8. Without that the line came out 688px wide under an 860px
    column (browser check, Phase 3)."""
    rule = css().split("#doc .credit {", 1)[1].split("}", 1)[0]
    assert "font-size: .8em" in rule
    assert "max-width: calc(57.3em / .8)" in rule
    assert "calc(1.73em / .8)" in rule


@test
def test_credit_is_one_centred_capsule():
    """Option D of the footer screen (Filip, 01.10.2026): four parts in one rounded
    capsule, centred under the text column, no dot separators."""
    c = credit(page())
    assert c.count('class="credit-seg') == 4, c
    assert "credit-sep" not in c and "·" not in c and "·" not in c
    cap = c.index('class="credit-capsule"')
    assert cap < c.index("MIT License") < c.index("GitHub") < c.index('id="open-settings"')
    rule = css().split("#doc .credit {", 1)[1].split("}", 1)[0]
    assert "justify-content: center" in rule and "max-width: calc(57.3em / .8)" in rule, rule
    capr = css().split(".credit-capsule {", 1)[1].split("}", 1)[0]
    assert "border-radius: 999px" in capr and "overflow: hidden" in capr, capr
    seg = css().split(".credit-seg + .credit-seg {", 1)[1].split("}", 1)[0]
    assert "border-left: 1px solid var(--line)" in seg, seg


@test
def test_glance_blocks_sit_tight_in_their_cells():
    c = css()
    assert '.sec[data-sec="__meta"] .glance-notes { margin-bottom: .9em; }' in c, "the lead sits above the table"
    assert '.sec[data-sec="__meta"] td > :first-child { margin-top: 0; }' in c
    assert '.sec[data-sec="__meta"] td > :last-child { margin-bottom: 0; }' in c


@test
def test_tooltips_can_be_switched_off():
    src = js()
    show = src.split("function showTip(el) {", 1)[1][:200]
    assert "if (!tipsOn) return;" in show, "the one tooltip function honours the setting"
    apply = src.split("function applyTipsSetting(s) {", 1)[1].split("\n  }", 1)[0]
    assert "show_tips !== false" in apply, "missing or unknown means on"
    assert "hideTip()" in apply, "switching off hides a tooltip already showing"
    remember = src.split("function rememberSettings(s) {", 1)[1].split("\n  }", 1)[0]
    assert "show_tips" in remember, "a page without the server uses the last value it heard"
    panel = src.split("function openSettings(btn, s) {", 1)[1].split("function wireSettings", 1)[0]
    assert 'box("Show tooltips", s.show_tips' in panel
    assert "show_tips: tips.checked" in panel
    assert "applyTipsSetting(res.settings)" in panel, "a save takes effect on this page at once"
    wire = src.split("function wire() {", 1)[1].split("\n  }", 1)[0]
    assert "applyTipsSetting(" in wire and "cachedShowTips()" in wire


@test
def test_pill_colours_and_peek():
    c = css()
    want = {"md": ("#F0844E", "#2a1608"), "html": ("#9FD3F2", "#0d3550"),
            "plan": ("#8E1B1B", "#fff"), "choice": ("#1F3A8A", "#fff")}
    for kind, (bg, ink) in want.items():
        rule = c.split('header .eyebrow[data-kind="%s"] {' % kind, 1)[1].split("}", 1)[0]
        assert "--pill-bg: %s;" % bg in rule and "--pill-ink: %s;" % ink in rule, kind
    base = c.split("header .eyebrow {", 1)[1].split("}", 1)[0]
    assert "border-radius: 999px" in base and "background: var(--pill-bg" in base
    # 1.0.2: the pill stays while a cut title is shown whole; only the controls go.
    assert "header.title-peek .eyebrow" not in c, "nothing hides the pill on peek"
    assert "transition" not in base, "the pill no longer animates"


@test
def test_finish_overlay_markup_and_copy():
    html = page()
    assert 'id="finish"' in html and 'role="dialog"' in html and 'aria-modal="true"' in html
    assert 'id="finish-close"' in html and 'data-tip="Close this page"' in html
    assert 'id="finish-cancel"' in html and 'data-tip="Go back to edit"' in html
    src = js()
    for s in ("Your approve prompt has been copied. Paste it back to Claude and close this page.",
              "Your decline prompt has been copied. Paste it back to Claude and close this page.",
              "Your change request has been copied. Paste it back to Claude and wait for this page to reload.",
              "Your browser keeps this tab open. Close it with "):
        assert s in src, s


@test
def test_box_opens_only_after_a_successful_copy():
    body = fn_body(js(), "finish")
    assert "copyText(text, function (ok)" in body
    assert "if (!ok || !FINISH_COPY[box]) return;" in body
    ct = fn_body(js(), "copyText")
    assert ct.count("if (then) then(") >= 2, "both the clipboard and the legacy path report back"


@test
def test_close_page_arms_like_reset():
    src = js()
    arm = fn_body(src, "armClose")
    assert "RESET_WINDOW_MS" in arm and '"Confirm"' in arm
    assert "Click again to close this page" in arm
    onc = fn_body(src, "onFinishClose")
    assert "window.close()" in onc and "setTimeout" in onc and "300" in onc
    assert "if (ev.key === \"Escape\" && finishOpen())" in src


@test
def test_copy_prompt_again_sits_left_of_the_buttons():
    html = page()
    box = html[html.index('id="finish"'):]
    assert box.index('class="finish-actions"') < box.index('id="finish-recopy"') < box.index('id="finish-cancel"'), \
        "the link opens the button row, left of Cancel"
    rule = css()[css().index(".finish-recopy {"):]
    rule = rule[:rule.index("}")]
    assert "margin-right: auto" in rule and "display: block" not in rule, rule
    assert 'data-tip="Copy the same prompt to the clipboard again"' in box
    assert ">Copy prompt again<" in box
    rc = fn_body(js(), "onFinishRecopy")
    assert "copyText(text, function (ok)" in rc
    assert '"Copied"' in rc and '"Copy failed. Cancel, then copy from the prompt pane"' in rc and "1500" in rc
    assert "{ keepPane: true }" in rc, "the recopy never opens the pane behind the backdrop"
    ct = fn_body(js(), "copyText")
    assert "function copyText(text, then, opts)" in ct
    assert "!(opts && opts.keepPane)" in ct, "the footer copies still open the pane on failure"
    assert "#finish-recopy" in css() or ".finish-recopy" in css()


@test
def test_overlay_css_blurs_and_respects_reduced_motion():
    c = css()
    assert "backdrop-filter: blur(6px)" in c
    blk = c[c.index("/* ---- finish overlay"):]
    assert "prefers-reduced-motion: reduce" in blk
    assert ".finish-box" in blk and "translateY(8px)" in blk


@test
def test_hidden_close_button_really_hides():
    assert "#finish-close[hidden] { display: none; }" in css()
    body = fn_body(js(), "openFinish")
    assert "if (!finishKind) finishFrom = doc.querySelector('.verdict[data-verdict=\"' +" in body
    assert "(c.verdict != null ? c.verdict : kind) + '\"]') || doc.activeElement;" in body, \
        "Cancel returns focus to the verdict button"


@test
def test_finish_boxes_draw_their_own_icon():
    html = page()
    box = html[html.index('id="finish"'):]
    for k in ("approve", "decline"):
        assert 'class="finish-ico fi-%s"' % k in box, k
    assert 'class="finish-ico fi-changes robot-stage"' in box
    assert box.index('class="robot-caption"') < box.index('id="finish-title"')
    assert "finish-dot" not in box and "finish-dot" not in css()
    c = css()
    assert "@keyframes finish-draw" in c and "stroke-dashoffset" in c
    for k in ("approve", "decline", "changes"):
        assert '.finish[data-kind="%s"] .fi-%s' % (k, k) in c, k
    rm = c[c.index("/* ---- finish overlay"):]
    rm = rm[rm.index("@media (prefers-reduced-motion: reduce)"):]
    rm = rm[:rm.index("\n}\n")]
    assert "animation: none" in rm and "stroke-dashoffset: 0" in rm, rm
    of = fn_body(js(), "openFinish")
    assert 'root.setAttribute("data-kind", kind)' in of


@test
def test_header_and_footer_stay_sharp_above_the_finish_box():
    c = css()
    assert "body.finishing header, body.finishing footer" in c
    rule = c[c.index("body.finishing header, body.finishing footer"):]
    rule = rule[:rule.index("}")]
    assert "z-index: 9001" in rule and "pointer-events: none" in rule and "position: relative" in rule, rule
    src = js()
    of = fn_body(src, "openFinish")
    assert 'body.classList.add("finishing")' in of and 'classList.add("title-peek")' in of
    cf = fn_body(src, "closeFinish")
    assert 'body.classList.remove("finishing")' in cf and 'classList.remove("title-peek")' in cf
    wp = fn_body(src, "wirePeek")
    assert "if (finishOpen()) return;" in wp, "leaving the title never drops the peek a box set"


@test
def test_closing_a_bubble_leaves_the_finish_box_open():
    # closeBubble runs on every window resize. It used to strip is-open from the
    # finish overlay too, which faded the box and blur out while the page still
    # treated the box as open.
    cb = fn_body(js(), "closeBubble")
    assert 'doc.querySelectorAll(".is-open:not(.finish)")' in cb, cb


@test
def test_choice_screens_get_a_finish_box_too():
    src = js()
    for t in ('options: { title: "Answer copied", close: true, verdict: "", forget: true,',
              '"Your answer has been copied. Paste it back to Claude and close this page."',
              'explain: { title: "Questions copied", close: true, verdict: "", forget: true,',
              '"Your questions have been copied. Paste them back to Claude and close this page."',
              'approve: { title: "Approved", close: true, forget: true,'):
        assert t in src, t
    body = fn_body(src, "finish")
    assert "var box = kind || D.meta.kind;" in body and "openFinish(box);" in body
    of = fn_body(src, "openFinish")
    assert "(c.verdict != null ? c.verdict : kind)" in of, "a screen's button has an empty verdict"
    assert "if (FINISH_COPY[finishKind].forget) forgetPage();" in fn_body(src, "onFinishClose")
    c = css()
    assert '.finish[data-kind="options"] .fi-approve' in c and '.finish[data-kind="explain"] .fi-approve' in c


@test
def test_settings_open_without_selecting_the_hours():
    body = fn_body(js(), "openSettings")
    assert "hours.select()" not in body, "the number is not highlighted on open"
    assert 'b.setAttribute("tabindex", "-1");' in body and "b.focus();" in body, "focus still lands in the panel"
    assert ".settings-panel:focus { outline: none; }" in css()


@test
def test_credit_names_part_is_always_highlighted():
    c = css()
    rule = c.split(".credit-seg:first-child {", 1)[1].split("}", 1)[0]
    assert "color: var(--link)" in rule and "background" not in rule, "the hover ink, no fill"
    top = c.split("#doc .credit {", 1)[1].split("}", 1)[0]
    assert "padding: 1.8em calc(1.73em / .8) 0;" in top, "twice the old .9em under the rule"


@test
def test_settings_wears_a_drawn_gear():
    c = credit(page())
    assert "&#9881;" not in c and "\u2699" not in c, "no text glyph, it renders differently per font"
    assert '<svg class="credit-gear" viewBox="0 0 16 16" aria-hidden="true">' in c
    rule = css().split(".credit-gear {", 1)[1].split("}", 1)[0]
    assert "stroke: currentColor" in rule and "fill: none" in rule, rule
    assert ".credit-settings:hover .credit-gear { transform: rotate(45deg); }" in css()
