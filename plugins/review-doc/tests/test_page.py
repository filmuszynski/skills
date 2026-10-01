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
    for part in ("/review-doc skill by Filip Muszyński", "MIT License", "v9.8.7", "GitHub", "Settings"):
        assert part in text, part
    assert "Muszynski" not in text, "the name is spelled with ń"
    assert 'href="https://github.com/filmuszynski"' in c
    assert 'href="%s"' % shell.LICENSE_URL in c and 'href="%s"' % shell.REPO_URL in c
    assert 'id="open-settings"' in c
    assert "—" not in c
    assert "credit-version" not in credit(page(version=None)), "no version, no 'v'"


@test
def test_credit_links_match_plugin_json():
    with io.open(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    assert shell.REPO_URL == manifest["homepage"]
    assert shell.AUTHOR_URL == manifest["author"]["url"]
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
    assert re.search(r'key: "html"[^}]*note: "arrives in v1\.1"[^}]*off: true', rows)
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
def test_credit_line_sits_left():
    """Centred in 1.0.1, back to the left in 1.0.2 (Filip, 01.10.2026)."""
    rule = css().split("#doc .credit {", 1)[1].split("}", 1)[0]
    assert "text-align" not in rule, "left, like the text above it"
    assert "max-width: calc(57.3em / .8)" in rule, "still on the text column"


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
    assert "if (!ok || !FINISH_COPY[kind]) return;" in body
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
def test_copy_prompt_again_sits_under_the_buttons():
    html = page()
    box = html[html.index('id="finish"'):]
    assert box.index('class="finish-actions"') < box.index('id="finish-recopy"')
    assert 'data-tip="Copy the same prompt to the clipboard again"' in box
    assert ">Copy prompt again<" in box
    rc = fn_body(js(), "onFinishRecopy")
    assert "copyText(text, function (ok)" in rc
    assert '"Copied"' in rc and '"Copy failed, use the prompt pane"' in rc and "1500" in rc
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
    assert ("if (!finishKind) finishFrom = doc.querySelector('.verdict[data-verdict=\"' + kind + '\"]')"
            " || doc.activeElement;") in body, "Cancel returns focus to the verdict button"
