# -*- coding: utf-8 -*-
"""Option and explainer screens.

Both kinds are one file rather than two, because they differ only in what a
`##` section becomes and how the answer is phrased. Everything above that, the
front matter, the section split and the markdown pipeline, is identical, and two
modules at eighty percent overlap is exactly the clone problem the shared shell
exists to avoid.

Source format:

    ---
    kind: options          # or: explain
    title: Where should the feedback live?
    select: one            # or: many        (options only)
    ---

    ## Sidebar
    <svg …>a diagram…</svg>
    Always visible, costs 400px.

    ## Overlay bubbles
    …

Raw HTML and inline SVG pass straight through, which is how a screen carries a
diagram rather than describing one.
"""
from __future__ import unicode_literals

import os
import re

from layout_plan import (MD_EXTENSIONS, RE_H2, _esc, _hash, _md, _strip_bom,
                         _tag_editables, slug_for)

KINDS = ("options", "explain")

RE_FRONT_KEY = re.compile(r"^([A-Za-z][A-Za-z_-]*)\s*:\s*(.*)$")

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# A screen has no verdict to set: on an options screen the choice is the answer
# and on an explainer the questions are. It still needs one way to finish, so it
# gets a single button that only copies.
# A Dingbat, from the same block as the tick and the cross, and measured to
# the same ink: 10px above the baseline and 1 below at 13px. The clipboard
# that was here is an emoji, so it kept its own colours and stayed a small
# coloured picture when the button filled, instead of turning white with
# the label.
COPY_ICON = "❐"

ACTIONS = {
    "options": [{"verdict": "", "icon": COPY_ICON, "label": "Copy answer",
                 "tip": "Copy your choice as a prompt for Claude",
                 "cls": "primary", "line": ""}],
    "explain": [{"verdict": "", "icon": COPY_ICON, "label": "Copy questions",
                 "tip": "Copy your questions as a prompt for Claude",
                 "cls": "primary", "line": ""}],
}


def parse(raw):
    """Screen Markdown to {kind, title, select, sections}."""
    text = _strip_bom(raw).replace("\r\n", "\n")
    meta, body = {}, text

    if text.startswith("---"):
        lines = text.split("\n")
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                for line in lines[1:i]:
                    m = RE_FRONT_KEY.match(line.strip())
                    if m:
                        meta[m.group(1).lower()] = m.group(2).strip()
                body = "\n".join(lines[i + 1:])
                break

    kind = meta.get("kind", "explain").lower()
    if kind not in KINDS:
        kind = "explain"
    select = meta.get("select", "one").lower()
    if select not in ("one", "many"):
        select = "one"

    sections, current, count = [], None, 0
    preamble = []

    def close():
        if current is not None:
            current["intro"] = "\n".join(current["lines"]).strip("\n")
            current["steps"] = []
            del current["lines"]
            sections.append(current)

    for line in body.split("\n"):
        m = RE_H2.match(line)
        if m:
            close()
            count += 1
            name = m.group(1).strip()
            num = ("Option " + LETTERS[(count - 1) % len(LETTERS)] if kind == "options"
                   else "Section " + str(count))
            current = {
                "id": _hash(kind + " " + name, "s"),
                "num": num,
                "name": name,
                "kind": "card" if kind == "options" else "section",
                "lines": [],
            }
            continue
        if current is not None:
            current["lines"].append(line)
        else:
            # Everything before the first heading. Without this it was silently
            # dropped, so a screen could not introduce its own question.
            preamble.append(line)

    close()

    seen = {}
    for sec in sections:
        if sec["id"] in seen:
            seen[sec["id"]] += 1
            sec["id"] = "%s-%d" % (sec["id"], seen[sec["id"]])
        else:
            seen[sec["id"]] = 0

    return {
        "kind": kind,
        "title": meta.get("title", "Screen"),
        "select": select,
        "preamble": "\n".join(preamble).strip("\n"),
        "sections": sections,
    }


# -------------------------------------------------------------------- render


def _card_html(sec, used, select):
    """A card is a section you can also pick.

    The pick control sits in the tag row rather than the whole card being
    clickable, so selecting a sentence to comment on cannot change the answer by
    accident.
    """
    return (
        '<div class="sec card" data-sec="%s" data-choice="%s">'
        '<div class="sec-tag pick-row" data-pick="%s">'
        '<span class="card-title">%s &middot; %s</span>'
        '<span class="sec-tools">'
        '<button class="pick" type="button" data-choice="%s" role="%s"'
        ' aria-checked="false" aria-label="Choose %s"></button>'
        "</span></div>%s</div>"
        % (_esc(sec["id"]), _esc(sec["id"]), _esc(sec["id"]),
           _esc(sec["num"].split()[-1]), _esc(sec["name"]),
           _esc(sec["id"]), "radio" if select == "one" else "checkbox",
           _esc(sec["name"]),
           _tag_editables(_md(sec["intro"]), sec["id"], used))
    )


def _section_html(sec, used):
    return (
        '<div class="sec" data-sec="%s">'
        '<div class="sec-tag"></div>'
        '<h2 data-edit-id="%s" data-sec="%s">%s</h2>%s</div>'
        % (_esc(sec["id"]),
           _esc(_hash(sec["id"] + "|heading", "e")), _esc(sec["id"]), _esc(sec["name"]),
           _tag_editables(_md(sec["intro"]), sec["id"], used))
    )


def build(raw, source, slug=None, generated_at=""):
    """Screen Markdown to the keyword arguments shell.render takes."""
    screen = parse(raw)
    used = set()
    kind = screen["kind"]
    source_disp = source.replace("\\", "/")

    rows, parts, lead = [], [], ""

    if screen["preamble"].strip():
        # A section like any other, so it can be commented on, but never a card:
        # the lead-in is not one of the things being chosen between.
        intro_id = _hash("intro " + screen["title"], "s")
        rows.append({"id": intro_id, "num": "Intro", "name": "", "kind": "intro", "steps": []})
        lead = ('<div class="sec lead" data-sec="%s">'
                '<div class="sec-tag"></div>%s</div>'
                % (_esc(intro_id), _tag_editables(_md(screen["preamble"]), intro_id, used)))

    for sec in screen["sections"]:
        rows.append({"id": sec["id"], "num": sec["num"], "name": sec["name"],
                     "kind": sec["kind"], "steps": []})
        parts.append(_card_html(sec, used, screen["select"]) if kind == "options"
                     else _section_html(sec, used))

    if kind == "options":
        body = '<div class="plain">' + lead + ('<div class="cards" data-select="%s">%s</div>'
                       % (_esc(screen["select"]), "".join(parts))) + "</div>"
        header = 'Answer to "%s" (%s):' % (screen["title"], source_disp)
        footer = ("Take the choice above as the decision and carry on. "
                  "If nothing was chosen, the note explains why none of them fit.")
        general = ("Anything the options do not cover"
                   if screen["select"] == "one" else "Anything to add")
    else:
        body = '<div class="plain">' + lead + "".join(parts) + "</div>"
        header = 'Questions on "%s" (%s):' % (screen["title"], source_disp)
        footer = ("Answer each of these. They are the parts that did not land, "
                  "so treat them as gaps in the explanation rather than as objections.")
        general = "Anything else that did not land"

    return {
        "title": screen["title"],
        "body_html": body,
        "sections": rows,
        "prompt_spec": {"header": header, "footer": footer},
        "meta": {
            "slug": slug or slug_for(source),
            "kind": kind,
            "source": source_disp,
            "generatedAt": generated_at,
        },
        "actions": ACTIONS[kind],
        "select": screen["select"],
        "general_placeholder": general,
    }
