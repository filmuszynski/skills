# -*- coding: utf-8 -*-
"""Prose documents: protocols, briefings, research notes, website copy.

The third layout, after plans and screens. It exists because a plan's structure
is not a document's: a plan is tasks and checkbox steps, a document is headings
and paragraphs, and rendering one as the other loses its opening line and calls
every block a task.

What a document gets that `layout_plan` would not give it:

  * everything before the first heading survives as a commentable lead block.
    `layout_plan.parse` drops it unless it matches `**Key:** value`, so a
    protocol lost the line naming who it was for.
  * `###` is a block in its own right, numbered 2.1 under its parent's 2 and
    carrying its own tick and pencil. In a plan a `###` is only a block when it
    reads `### Task N:`.
  * a file with no headings at all still renders, as one section. That case
    produced a blank page.
  * `**Key:** value` fields in the lead get the plan's At a glance box (1.1),
    but on the lead block's real id. `layout_plan._meta_html` hangs its table
    off `data-sec="__meta"`, which never appears in the `sections` list, and
    `buildPrompt` only prints marks whose section it finds there, so a comment
    on that box is stored and silently never sent. The lead's id has no such
    hole.

Sections are flat. A subsection is a sibling that indents, not a child, which is
what lets every mechanism in the shell work on it unchanged.
"""
from __future__ import unicode_literals

import os
import re

import shell
from layout_common import facts_rows
from layout_plan import (RE_FENCE, RE_H2, _esc, _fence_marks, _hash, _md,
                         _render_block, _strip_bom, _strip_front_matter,
                         _trim_block, header_blocks)

RE_H3 = re.compile(r"^###\s+(.+?)\s*$")

EYEBROWS = {"section": "Section", "sub": "Subsection", "intro": "Intro"}

# Two, not three. Decline on a plan means "rethink the approach"; on a draft
# there is no approach to rethink, only text to change, so it would collapse
# into Request changes. The lines are the plan's, reworded for a document.
ACTIONS = [
    {"verdict": "approve", "icon": "✓", "label": "Approve", "cls": "approve",
     "tip": "Approve the document and copy the prompt for Claude",
     "line": "VERDICT: approved. The document is finished. Apply anything marked "
             "below and do not come back for another review.",
     # With nothing marked, "apply anything below" and the how-to-apply footer
     # would be instructions about nothing, so the prompt stops here.
     "bare": "VERDICT: approved. The document is finished."},
    {"verdict": "changes", "icon": "", "icon_cls": shell.LOOP_CLS,
     "label": "Request changes", "cls": "changes",
     "tip": "Ask for a revised document and copy the prompt for Claude",
     "line": "VERDICT: revise and re-present. Apply everything below and regenerate "
             "the page; the open page reloads by itself."},
]


def parse(raw):
    """Document Markdown to {title, preamble, sections}."""
    text = _strip_front_matter(_strip_bom(raw)).replace("\r\n", "\n")

    title = ""
    sections, current = [], None
    preamble = []
    top, sub = 0, 0
    in_fence = False

    def close():
        if current is None:
            return
        current["intro"] = "\n".join(current["lines"]).strip("\n")
        current["steps"] = []
        del current["lines"]
        sections.append(current)

    for line in text.split("\n"):
        if RE_FENCE.match(line):
            in_fence = not in_fence

        if not in_fence:
            if not title and line.startswith("# "):
                title = line[2:].strip()
                continue

            m3 = RE_H3.match(line)
            if m3:
                close()
                name = m3.group(1).strip()
                # A `###` before any `##` has no parent to be 0.1 of, so it is
                # promoted rather than numbered against nothing.
                if top == 0:
                    top += 1
                    kind, index = "section", str(top)
                else:
                    sub += 1
                    kind, index = "sub", "%d.%d" % (top, sub)
                current = {"id": _hash(kind + " " + name, "s"),
                           "num": EYEBROWS[kind] + " " + index, "index": index,
                           "name": name, "kind": kind, "lines": []}
                continue

            m2 = RE_H2.match(line)
            if m2:
                close()
                top += 1
                sub = 0
                name = m2.group(1).strip()
                current = {"id": _hash("sec " + name, "s"),
                           "num": "Section " + str(top), "index": str(top),
                           "name": name, "kind": "section", "lines": []}
                continue

        if current is not None:
            current["lines"].append(line)
        else:
            preamble.append(line)

    close()

    lead = "\n".join(preamble).strip("\n")

    # A document with no headings is still a document. Without this it rendered
    # a page with a title and nothing under it.
    if not sections and lead.strip():
        # Named only if the file actually carried a title. Otherwise the "Document"
        # fallback would be printed as a heading the document never had.
        name = title or ""
        sections.append({"id": _hash("sec " + (name or lead[:80]), "s"),
                         "num": "Section 1", "index": "1", "name": name,
                         "kind": "section", "intro": lead, "steps": []})
        lead = ""

    seen = {}
    for sec in sections:
        if sec["id"] in seen:
            seen[sec["id"]] += 1
            sec["id"] = "%s-%d" % (sec["id"], seen[sec["id"]])
        else:
            seen[sec["id"]] = 0

    return {"title": title or "Document", "preamble": lead,
            "preamble_lines": preamble, "sections": sections}


# ------------------------------------------------------------------- render


def _section_html(sec, used):
    """A block and its two controls in the tag row.

    The same markup a plan section uses, minus the steps, the margin ring and
    the eyebrow. A document reads as prose, so its headings carry it on their
    own; the section number still reaches the feedback through `rows`.
    """
    kind = sec["kind"]
    parts = ['<div class="sec%s" data-sec="%s" data-kind="%s">'
             % (" lead" if kind == "intro" else "", _esc(sec["id"]), _esc(kind))]

    named = sec["name"] or "the introduction"
    parts.append(
        '<div class="sec-tag"><span class="sec-tools">'
        '<button class="note-btn" type="button" data-for="%s" data-has-note="no"'
        ' aria-label="Add a note on %s">&#9998;</button>'
        '<button class="dec" type="button" data-for="%s" data-decision=""'
        ' aria-label="%s: undecided, click to approve">?</button>'
        '</span></div>'
        % (_esc(sec["id"]), _esc(named),
           _esc(sec["id"]), _esc(named)))

    if kind != "intro" and sec["name"]:
        # h3 for a subsection, so the document keeps its own hierarchy in type
        # as well as in the margin. Both tags are already rewritable.
        tag = "h3" if kind == "sub" else "h2"
        parts.append('<%s data-edit-id="%s" data-sec="%s">%s</%s>'
                     % (tag, _esc(_hash(sec["id"] + "|heading", "e")),
                        _esc(sec["id"]), _esc(sec["name"]), tag))

    body = _render_block(sec["intro"], sec["id"], used)
    if body:
        parts.append(body)

    parts.append("</div>")
    return "\n".join(parts)


def _shows_something(text):
    """Does this preamble put anything on the page?

    An HTML comment such as `<!-- generated -->` often opens a generated file.
    It is an instruction to a tool, not content, and it renders to nothing, so a plain `.strip()` on the source produced an Intro
    block that was an empty bordered box with a tick and a pencil in it.
    """
    if not text or not text.strip():
        return False
    html = re.sub(r"<!--.*?-->", "", _md(text), flags=re.S)
    return bool(re.sub(r"<[^>]+>", "", html).strip())


def slug_for_path(source):
    """Parent folder plus file name.

    `layout_plan.slug_for` takes the basename alone, which is fine for
    `.claude/plans/` where every name is dated and unique. Documents are often
    called README.md in different folders, so the parent folder comes along or
    the second one silently overwrites the first.
    """
    norm = (source or "document").replace("\\", "/").rstrip("/")
    parts = [p for p in norm.split("/") if p not in ("", ".", "..")]
    base = re.sub(r"\.md$", "", parts[-1] if parts else "document", flags=re.I)
    if len(parts) > 1:
        base = parts[-2] + "-" + base
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-._").lower()
    return base or "document"


def _glance_html(intro, lines, used, facts=None):
    """The plan's At a glance box, on the lead block's real id, so a comment on
    it reaches the prompt (the plan box's __meta id never did). None when the
    lead has no **Key:** line."""
    lines = [l.rstrip("\n") for l in lines]
    fenced = _fence_marks(lines)
    notes, meta = header_blocks(lines, fenced)
    if not meta:
        return None
    sid = intro["id"]
    rows = "".join(
        "<tr><th>%s</th><td>%s</td></tr>"
        % (_esc(k), _render_block(_trim_block(v), sid, used))
        for k, v in meta.items()) + facts_rows(facts)
    lead = _trim_block(notes)
    lead_html = ('<div class="glance-notes">%s</div>' % _render_block(lead, sid, used)
                 if lead.strip() else "")
    return ('<div class="sec lead glance" data-sec="%s" data-kind="intro">'
            '<div class="sec-tag"><span class="sec-tools">'
            '<button class="note-btn" type="button" data-for="%s" data-has-note="no"'
            ' aria-label="Add a note on the introduction">&#9998;</button>'
            '<button class="dec" type="button" data-for="%s" data-decision=""'
            ' aria-label="the introduction: undecided, click to approve">?</button>'
            '</span></div><h2>At a glance</h2>%s<table>%s</table></div>'
            % (_esc(sid), _esc(sid), _esc(sid), lead_html, rows))


def _facts_box(facts):
    """A box of facts only, for a document without **Key:** lines. Same markup as a
    plan's box: nothing in it to judge, so no tick and no pencil."""
    return ('<div class="sec" data-sec="__meta"><div class="sec-tag"></div>'
            "<h2>At a glance</h2><table>%s</table></div>" % facts_rows(facts))


def build(raw, source, slug=None, generated_at="", facts=None):
    """Document Markdown to the keyword arguments shell.render takes."""
    doc = parse(raw)
    used = set()
    source_disp = source.replace("\\", "/")

    body, rows = [], []

    if _shows_something(doc["preamble"]):
        intro = {"id": _hash("intro " + doc["title"], "s"), "num": "Intro",
                 "index": "", "name": "", "kind": "intro",
                 "intro": doc["preamble"], "steps": []}
        rows.append({"id": intro["id"], "num": "Intro", "name": "",
                     "kind": "intro", "steps": []})
        glance = _glance_html(intro, doc["preamble_lines"], used, facts)
        if glance is None and facts:
            body.append(_facts_box(facts))
        body.append(glance or _section_html(intro, used))
    elif facts:
        body.append(_facts_box(facts))

    for sec in doc["sections"]:
        body.append(_section_html(sec, used))
        rows.append({"id": sec["id"], "num": sec["num"], "name": sec["name"],
                     "kind": sec["kind"], "steps": []})

    footer = (
        "Apply the changes directly in %s, then render its review page again with "
        "review-doc and hand over the link. "
        "Everything not mentioned stays as it is." % source_disp
    )

    joined = '<div class="plain">' + chr(10).join(p for p in body if p) + "</div>"

    return {
        "title": doc["title"],
        "body_html": joined,
        "sections": rows,
        "prompt_spec": {
            "header": 'Review of the document "%s" (%s):' % (doc["title"], source_disp),
            "footer": footer,
            # The shell says "Whole plan" by default, which is wrong on a
            # protocol. Every layout now names its own whole.
            "generalLabel": "Whole document",
        },
        "actions": ACTIONS,
        "meta": {
            "slug": slug or slug_for_path(source),
            "kind": "doc",
            "source": source_disp,
            "generatedAt": generated_at,
        },
        "general_placeholder": "A note on the whole document, optional",
    }
