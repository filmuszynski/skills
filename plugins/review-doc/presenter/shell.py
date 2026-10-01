# -*- coding: utf-8 -*-
"""The presenter shell: chrome, state, undo, comments, transport.

A layout produces five things and knows nothing about any of the above:

    shell.render(title, body_html, sections, prompt_spec, meta,
                 actions=None, select=None, general_placeholder=None) -> str

    title         str   shown in the header and the browser tab
    body_html     str   the document itself, honouring the markup contract in shell.js
    sections      list  [{id, num, name, kind, steps}] mirroring what is in body_html.
                        Not rendered directly: it is how the prompt names a section
                        or a step that carries a decision.
    prompt_spec   dict  {header, footer} wrapped around the assembled answer,
                        plus generalLabel, what the free-text note is a note on
    meta          dict  {slug, kind, source, generatedAt, sourceMtime?, version?}
                        sourceMtime (epoch ms) is added by build_screen.py; without
                        it the page never checks whether its source moved on;
                        version is the plugin version, shown in the credit line
    actions       list  the footer buttons that send, [{verdict, label, cls, line}].
                        A plan offers approve/changes/decline; an options screen
                        offers one Send answer, because choosing IS the answer.
    select        str   'one' or 'many' for an options screen, else None
    general_placeholder str  what the free-text box invites

The result is one self-contained file: no external script, stylesheet or font.
"""
from __future__ import unicode_literals

import io
import json
import os
import re
import tempfile

import paths

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")

# The credit line's links. test_credit_links_match_plugin_json keeps them equal to
# the manifest's homepage and author.
AUTHOR_URL = "https://github.com/filmuszynski"
REPO_URL = "https://github.com/filmuszynski/skills"
LICENSE_URL = REPO_URL + "/blob/main/LICENSE"

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
__CSS__
</style>
</head>
<body class="mode-comment prompt-hidden">
<header>
  <span class="eyebrow" data-kind="__PILL__">__KIND__</span>
  <span class="doc-title">__SHORT__</span>
  <div class="spacer"></div>
  <div class="controls-slot"><div class="controls">
  <div class="counters" role="group" aria-label="Jump through your feedback">
    <button class="counter" data-kind="comments" type="button" disabled><svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 3.5h10a1.2 1.2 0 0 1 1.2 1.2v5.1a1.2 1.2 0 0 1-1.2 1.2H7.2L4.4 13.4V11H3a1.2 1.2 0 0 1-1.2-1.2V4.7A1.2 1.2 0 0 1 3 3.5z"/></svg><span class="num">0</span></button>
    <button class="counter" data-kind="edits" type="button" disabled><svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><path d="M10.6 2.6l2.8 2.8-7.9 7.9H2.7v-2.8z"/><path d="M9.1 4.1l2.8 2.8"/></svg><span class="num">0</span></button>
    <button class="counter" data-kind="all" type="button" disabled><svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.6 14.2V2.4"/><path d="M3.6 2.9h8.6l-2 2.9 2 2.9H3.6"/></svg><span class="num">0</span></button>
  </div>
  <div class="modes" role="group" aria-label="Review mode">
    <button type="button" data-mode="comment" data-label="Comment" aria-pressed="true"
            data-tip="Select any passage to comment on it">Comment</button>
    <button type="button" data-mode="edit" data-label="Edit text" aria-pressed="false"
            data-tip="Click into the text and rewrite it in place">Edit text</button>
  </div>
  <div class="history">
    <button class="iconbtn" id="undo" type="button" data-tip="Undo (Ctrl+Z)" aria-label="Undo">&#8630;</button>
    <button class="iconbtn" id="redo" type="button" data-tip="Redo (Ctrl+Y)" aria-label="Redo">&#8631;</button>
    <button class="iconbtn" id="reset" type="button"
            data-tip="Clear every comment, rewrite and decision. Ctrl+Z brings it back."
            aria-label="Reset the review"><span class="ico-reset" aria-hidden="true"></span></button>
  </div>
  </div></div>
</header>
<div id="stale" class="stale" role="status" hidden>
  <span>The source has changed since this page was built.</span>
  <button type="button" class="btn small" id="stale-reload">Reload</button>
</div>
<div id="orphans" class="orphans" hidden></div>
<main>
  <div id="doc">
__BODY__
__CREDIT__
  </div>
</main>
<footer>
  <div class="prompt-row">
    <pre id="prompt" class="is-empty"></pre>
  </div>
  <div class="verdict-row">
    <button class="iconbtn toggle" id="t-prompt" type="button" aria-expanded="false"
            aria-controls="prompt" data-tip="Show prompt">&#9652;</button>
    <input id="general" class="general" type="text"
           placeholder="__GENERAL__" aria-label="__GENERAL__"
           data-tip="A note on the whole thing rather than one passage. It goes at the top of the prompt">
    <span id="status"><span class="status-text"></span></span>
    <div class="verdicts" role="group" aria-label="Finish the review">
__ACTIONS__
    </div>
  </div>
</footer>
<div id="finish" class="finish" hidden>
  <div class="finish-backdrop"></div>
  <div class="finish-box" role="dialog" aria-modal="true" aria-labelledby="finish-title"
       aria-describedby="finish-text">
    <h2 id="finish-title"><span class="finish-dot" aria-hidden="true"></span><span class="finish-title-text"></span></h2>
    <p id="finish-text"></p>
    <div class="finish-actions">
      <button type="button" class="btn" id="finish-cancel" data-tip="Go back to edit">Cancel</button>
      <button type="button" class="btn primary" id="finish-close" data-tip="Close this page"
              data-label="Confirm"><span class="lbl">Close page</span></button>
    </div>
    <button type="button" class="finish-recopy" id="finish-recopy"
            data-tip="Copy the same prompt to the clipboard again">Copy prompt again</button>
  </div>
</div>
<script>
/* Assigned onto window on purpose. A top-level `const` in a classic script
   lives in the global lexical environment and never becomes a window
   property, so shell.js would read undefined. */
window.PRESENTER_DATA = __DATA__;
</script>
<script>
__JS__
</script>
</body>
</html>
"""


def _asset(name):
    with io.open(os.path.join(ASSETS, name), encoding="utf-8") as fh:
        return fh.read()


def _esc(text):
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))


def _json_literal(payload):
    """JSON safe to drop inside a <script> block.

    A bare </script> anywhere in the payload would close the block early, which
    is how a section title quoting HTML silently breaks the page.
    """
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def _credit_html(version):
    """The last line of every page: who made it, the license, the version, the repo,
    and the way into the settings.

    It is chrome, not document: no data-edit-id, no section, so it can never be
    rewritten, and the page ignores a selection that touches it. The settings button
    and its separator sit in .credit-tail, which print hides.
    """
    sep = '<span class="credit-sep" aria-hidden="true">·</span>'
    link = '<a href="{0}" target="_blank" rel="noopener">{1}</a>'
    parts = ["/review-doc skill by " + link.format(AUTHOR_URL, "Filip Muszyński"),
             link.format(LICENSE_URL, "MIT License")]
    if version:
        parts.append('<span class="credit-version">v%s</span>' % _esc(version))
    parts.append(link.format(REPO_URL, "GitHub&nbsp;&#8599;"))
    tail = ('<span class="credit-tail">' + sep +
            '<button type="button" class="credit-settings" id="open-settings" '
            'aria-haspopup="dialog" data-tip="Settings for every review page">'
            '<span aria-hidden="true">&#9881;</span> Settings</button></span>')
    return '<div class="credit">' + sep.join(parts) + tail + "</div>"


PENCIL = "✎"
# Request changes sends the plan round again, so it wears a loop rather than a
# pencil. The pencil stays the mark of editing, on the note control in the
# document, where it means writing something rather than going round.
#
# The loop is artwork rather than a character. Every circle-arrow in the font
# the tick and the cross come from is drawn smaller and heavier than they are,
# and no CSS correction fixed that convincingly, so this one is a chosen image
# masked in `.ico-loop` and painted with currentColor like the other two.
LOOP_CLS = "ico-loop"

# Trailing words that say what the document is rather than what it is about.
# The kind is already shown beside the title, so repeating it wastes the space
# the header was trimmed to gain.
_TITLE_TAIL = re.compile(
    r"(?:[\s:,-]+)(implementation\s+plan|design\s+doc(?:ument)?|plan|design|spec(?:ification)?|report|review)\s*$",
    re.I)


def short_title(title, cap=42):
    """A header-sized version of the document title.

    Falls back to the full title rather than returning something empty, because
    a document called just "Plan" would otherwise lose its name entirely.
    """
    text = re.sub(r"\s+", " ", (title or "").strip())
    trimmed = _TITLE_TAIL.sub("", text).strip()
    out = trimmed or text
    if len(out) > cap:
        out = out[:cap - 1].rstrip() + "…"
    return out


PLAN_ACTIONS = [
    # The three have to instruct differently or the chips are decoration. The
    # distinction that matters on a long plan is whether to keep going or come
    # back, so approve and changes say so in as many words. Both once read
    # "apply what is below and carry on", which made them the same verdict.
    #
    # Approve and decline are the two answers that end the review, so they sit
    # together. Request changes is the one that asks for another round, and it
    # is also the one that can be unavailable, so it goes last where a greyed
    # button does not leave a hole between two live ones.
    {"verdict": "approve", "icon": "✓", "label": "Approve", "cls": "approve",
     "tip": "Approve the plan and copy the prompt for Claude",
     "line": "VERDICT: approved. Build it, applying anything marked below. "
             "No second review needed, go straight to work.",
     # Nothing marked: no "anything below" and no how-to-apply footer.
     "bare": "VERDICT: approved. Build it as written. "
             "No second review needed, go straight to work."},
    {"verdict": "decline", "icon": "✗", "label": "Decline", "cls": "decline",
     "tip": "Reject the approach and copy the prompt for Claude",
     "line": "VERDICT: declined. Do not build this and do not patch it. "
             "Rethink the approach and come back with a different one."},
    {"verdict": "changes", "icon": "", "icon_cls": LOOP_CLS,
     "label": "Request changes", "cls": "changes",
     "tip": "Ask for a revised plan and copy the prompt for Claude",
     "line": "VERDICT: revise and re-present. Apply everything below, regenerate the "
             "page and give me the link again. Do not start building until I have "
             "seen the revision."},
]


def _actions_html(actions):
    """One button per way of finishing, with the icon in its own span.

    Each one copies. A plan's three also set a verdict first, so the copied text
    leads with it; a screen has a single button that only copies, because the
    choice or the questions already are the answer.

    The span is what lets the pencil be mirrored without mirroring the label
    along with it.
    """
    out = []
    for a in actions:
        icon = a.get("icon", "")
        cls = "ico ico-pen" if icon == PENCIL else "ico"
        if a.get("icon_cls"):
            cls += " " + a["icon_cls"]
        out.append(
            '      <button class="chip verdict {c}" data-verdict="{v}" type="button" '
            'aria-pressed="false" data-tip="{tip}" data-tip-base="{tip}">'
            '<span class="{ic}" aria-hidden="true">{icon}</span> {label}</button>'.format(
                c=_esc(a.get("cls", "send")), v=_esc(a["verdict"]), tip=_esc(a.get("tip", "")),
                ic=cls, icon=_esc(icon), label=_esc(a["label"]))
        )
    return chr(10).join(out)


# What the header's pill says, and which colour it wears. A document page names its
# file type, a plan or a choice screen names what it is; meta.kind itself is unchanged.
# Both screen kinds are one switch in the settings, so they are one pill too.
EYEBROW_LABEL = {"doc": "MD", "html": "HTML", "plan": "PLAN",
                 "options": "CHOICE", "explain": "CHOICE"}
PILL_KIND = {"doc": "md", "html": "html", "plan": "plan",
             "options": "choice", "explain": "choice"}


def render(title, body_html, sections, prompt_spec, meta,
           actions=None, select=None, general_placeholder=None):
    # None means "not supplied, use the default". An empty list means "this kind
    # has no verdict", which is not the same thing and must not fall back.
    actions = PLAN_ACTIONS if actions is None else list(actions)
    data = {
        "sections": list(sections),
        "prompt": {
            "header": prompt_spec.get("header", "Feedback:"),
            "footer": prompt_spec.get("footer", ""),
            # What the free-text note is a note *on*. A plan has a whole plan,
            # a document a whole document; the default keeps every existing
            # page byte-identical.
            "generalLabel": prompt_spec.get("generalLabel", "Whole plan"),
        },
        "meta": dict(meta),
        "actions": actions,
        "select": select or "one",
    }

    out = PAGE
    out = out.replace("__CREDIT__", _credit_html(meta.get("version")))
    out = out.replace("__CSS__", _asset("shell.css"))
    out = out.replace("__DATA__", _json_literal(data))
    out = out.replace("__JS__", _asset("shell.js"))
    out = out.replace("__BODY__", body_html)
    out = out.replace("__ACTIONS__", _actions_html(actions))
    out = out.replace("__GENERAL__", _esc(general_placeholder or "A note on the whole plan, optional"))
    kind = meta.get("kind", "document")
    out = out.replace("__PILL__", _esc(PILL_KIND.get(kind, "")))
    out = out.replace("__KIND__", _esc(EYEBROW_LABEL.get(kind, kind)))
    # Not cut to length: the header shortens it with an ellipsis while the
    # counters show, and widens to the whole name when they slide away.
    out = out.replace("__SHORT__", _esc(short_title(title, cap=400)))
    out = out.replace("__TITLE__", _esc(title))
    return out


def write(path, html):
    """Write through a uniquely named temp file and rename, so a reader never sees
    half a page and two renders of one page cannot interleave."""
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    fd, tmp = tempfile.mkstemp(prefix=".page-", suffix=".tmp", dir=directory or None)
    os.close(fd)
    try:
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(html)
        paths.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return path
