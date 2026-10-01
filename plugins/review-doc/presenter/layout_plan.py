# -*- coding: utf-8 -*-
"""Plan Markdown to the five things the shell wants.

Handles both plan shapes that occur in this repo:

  * the writing-plans template, with `### Task N:` blocks and `- [ ]` steps
  * plain reports, with nothing but `##` headings

Identity is content, never position. A section is keyed by a hash of its
heading, a step by a hash of its text. Inserting a task above another one
therefore leaves every existing comment where it was, which a position-keyed
review page gets wrong.
"""
from __future__ import unicode_literals

import os
import re

import layout_tables
import shell
from layout_common import (MD_EXTENSIONS, _esc, _hash, _mask_pre, _md,  # noqa: F401
                           _unmask_pre)


RE_TASK = re.compile(r"^###\s+Task\s+(\d+)\s*[:.]\s*(.+?)\s*$", re.I)
RE_H2 = re.compile(r"^##\s+(.+?)\s*$")
RE_STEP = re.compile(r"^-\s+\[[ xX]\]\s+(.*)$")
RE_META = re.compile(r"^\*\*([A-Za-z][A-Za-z ]*?):\*\*\s*(.*)$")
RE_FENCE = re.compile(r"^\s*(```|~~~)")
# A line that starts a block of its own never continues the field above it.
RE_NOT_WRAP = re.compile(r"^\s*(#|>|[-*+]\s|\d+[.)]\s|\||```|~~~|-{3,}\s*$|\*{3,}\s*$|_{3,}\s*$)")
AGENTIC_BANNER = "> **For agentic workers:**"
RE_RULE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
RE_BOLD_LEAD = re.compile(r"^\*\*(.+?)\*\*:?\s*")

EDITABLE_TAGS = ("p", "h2", "h3", "h4", "td", "th")


def _strip_bom(text):
    return text[1:] if text[:1] == "﻿" else text


def _strip_front_matter(text):
    if not text.startswith("---"):
        return text
    parts = text.split("\n")
    if parts[0].strip() != "---":
        return text
    for i in range(1, len(parts)):
        if parts[i].strip() == "---":
            return "\n".join(parts[i + 1:])
    return text


def _split_steps(body_lines):
    """Split a task body into an intro and its steps, respecting code fences."""
    intro, steps, current, in_fence = [], [], None, False
    for line in body_lines:
        if RE_FENCE.match(line):
            in_fence = not in_fence
        m = None if in_fence else RE_STEP.match(line)
        if m:
            if current is not None:
                steps.append(current)
            current = [m.group(1)]
        elif current is not None:
            current.append(line)
        else:
            intro.append(line)
    if current is not None:
        steps.append(current)

    out = []
    for chunk in steps:
        md_text = "\n".join(chunk).strip("\n")
        name = RE_BOLD_LEAD.match(chunk[0])
        out.append({
            "id": _hash(md_text, "t"),
            "name": (name.group(1) if name else chunk[0]).strip(),
            "md": md_text,
        })
    return "\n".join(intro).strip("\n"), out


def parse(raw):
    """Markdown text to {title, meta, sections}."""
    text = _strip_front_matter(_strip_bom(raw)).replace("\r\n", "\n")
    lines = text.split("\n")

    title, meta, last_meta = "", {}, None
    preamble, in_banner = [], False
    sections, current = [], None
    plain_count = 0
    in_fence = False

    def close():
        if current is None:
            return
        body = "\n".join(current["lines"]).strip("\n")
        if current["kind"] == "task":
            intro, steps = _split_steps(body.split("\n"))
        else:
            intro, steps = body, []
        current["intro"] = intro
        current["steps"] = steps
        del current["lines"]
        sections.append(current)

    for line in lines:
        fence = RE_FENCE.match(line)
        if fence:
            in_fence = not in_fence
        # A code block before the first section goes to the preamble whole: the
        # opening line (in_fence just turned True), the lines inside, and the
        # closing line (fence matched, in_fence back to False). Each exactly once.
        if current is None and title and (in_fence or fence):
            preamble.append(line)
            last_meta = None
            continue

        if not in_fence:
            if not title and line.startswith("# "):
                title = line[2:].strip()
                continue

            mt = RE_TASK.match(line)
            if mt:
                close()
                name = mt.group(2).strip()
                current = {"id": _hash("task " + name, "s"), "num": "Task " + mt.group(1),
                           "index": mt.group(1),
                           "name": name, "kind": "task", "lines": []}
                continue

            mh = RE_H2.match(line)
            if mh:
                close()
                plain_count += 1
                name = mh.group(1).strip()
                # "1" alone said nothing. The prompt reads better for it too:
                # "Section 1 (Context)" rather than "1 (Context)".
                current = {"id": _hash("sec " + name, "s"), "num": "Section " + str(plain_count),
                           "index": str(plain_count),
                           "name": name, "kind": "section", "lines": []}
                continue

            if current is None:
                mm = RE_META.match(line)
                if mm:
                    last_meta, in_banner = mm.group(1).strip(), False
                    meta[last_meta] = mm.group(2).strip()
                    continue
                if last_meta and line.strip() and not RE_NOT_WRAP.match(line):
                    # A field wrapped over several lines: plans wrap at about 90 columns.
                    meta[last_meta] = (meta[last_meta] + " " + line.strip()).strip()
                    continue
                last_meta = None
                # The writing-plans banner speaks to the executing agent; it is not
                # part of what is reviewed. Everything else after the title is kept,
                # so a quote or a list under a field reaches the page.
                if line.startswith(AGENTIC_BANNER):
                    in_banner = True
                if in_banner:
                    if line.startswith(">"):
                        continue
                    in_banner = False
                if title:
                    preamble.append(line)
                continue

        if current is not None:
            current["lines"].append(line)

    close()

    seen = {}
    for sec in sections:
        if sec["id"] in seen:
            seen[sec["id"]] += 1
            sec["id"] = "%s-%d" % (sec["id"], seen[sec["id"]])
        else:
            seen[sec["id"]] = 0

    # A rule at either end only frames the header; it is not content to show.
    while preamble and (not preamble[0].strip() or RE_RULE.match(preamble[0])):
        preamble.pop(0)
    while preamble and (not preamble[-1].strip() or RE_RULE.match(preamble[-1])):
        preamble.pop()

    return {"title": title or "Plan", "meta": meta, "sections": sections,
            "preamble": "\n".join(preamble)}


# ------------------------------------------------------------------- render


def _tag_editables(html, sec_id, used):
    """Mark prose elements as rewritable.

    The id hashes the element's first text run rather than its position, so
    inserting a paragraph above an edited one does not move the edit.
    """
    html, pre_blocks = _mask_pre(html)

    def attrs(lead_text, fallback):
        base = _hash(sec_id + "|" + (lead_text or fallback), "e")
        eid = base
        n = 1
        while eid in used:
            n += 1
            eid = "%s-%d" % (base, n)
        used.add(eid)
        return ' data-edit-id="%s" data-sec="%s"' % (eid, sec_id)

    counter = [0]

    def tag(m):
        counter[0] += 1
        tag_name, rest, after = m.group(1), m.group(2), m.group(3)
        if tag_name == "li" and after.lstrip().startswith("<p"):
            return m.group(0)
        lead = re.split(r"<", after, 1)[0].strip()
        return "<%s%s%s>%s" % (tag_name, rest, attrs(lead, "%s%d" % (tag_name, counter[0])), after)

    pattern = r"<(%s|li)((?:\s[^>]*)?)>([^<]*)" % "|".join(EDITABLE_TAGS)
    html = re.sub(pattern, tag, html)
    return _unmask_pre(html, pre_blocks)


def _render_block(md_text, sec_id, used):
    """Markdown to review HTML: rewritable elements first, then table identity.

    Order matters: `stamp_tables` inserts its attributes right after `<td` and
    `<th`, so the edit ids `_tag_editables` added stay where they are.
    """
    html = _tag_editables(_md(md_text), sec_id, used)
    return layout_tables.stamp_tables(html, md_text, sec_id, used)


def _section_html(sec, used):
    parts = ['<div class="sec" data-sec="%s" data-kind="%s">'
             % (_esc(sec["id"]), _esc(sec["kind"]))]
    # The document style: no ring in the margin and no eyebrow. The heading
    # carries the block, and the number still reaches the feedback via `rows`.
    parts.append(
        '<div class="sec-tag"><span class="sec-tools">'
        '<button class="note-btn" type="button" data-for="%s" data-has-note="no"'
        ' aria-label="Add a note on %s">&#9998;</button>'
        '<button class="dec" type="button" data-for="%s" data-decision=""'
        ' aria-label="%s: undecided, click to approve">?</button>'
        '</span></div>'
        % (_esc(sec["id"]), _esc(sec["name"]),
           _esc(sec["id"]), _esc(sec["name"])))
    parts.append('<h2 data-edit-id="%s" data-sec="%s">%s</h2>'
                 % (_esc(_hash(sec["id"] + "|heading", "e")), _esc(sec["id"]), _esc(sec["name"])))

    intro = _render_block(sec["intro"], sec["id"], used)
    if intro:
        parts.append(intro)

    for step in sec["steps"]:
        body = _render_block(step["md"], sec["id"], used)
        parts.append(
            '<div class="step" data-step="%s" data-decision="">'
            '<button class="dec" type="button" data-for="%s" data-decision="" '
            'aria-label="%s: undecided, click to approve">?</button>'
            '<div class="step-body">%s</div></div>'
            % (_esc(step["id"]), _esc(step["id"]), _esc(step["name"]), body)
        )

    parts.append("</div>")
    return "\n".join(parts)


def _meta_html(plan):
    notes = plan.get("preamble", "")
    if not plan["meta"] and not notes:
        return ""
    rows = "".join(
        "<tr><th>%s</th><td>%s</td></tr>" % (_esc(k), _md(v).replace("<p>", "").replace("</p>", ""))
        for k, v in plan["meta"].items()
    )
    table = "<table>%s</table>" % rows if rows else ""
    extra = '<div class="glance-notes">%s</div>' % _md(notes) if notes else ""
    return ('<div class="sec" data-sec="__meta"><div class="sec-tag"></div>'
            "<h2>At a glance</h2>%s%s</div>" % (table, extra))


def slug_for(source):
    base = os.path.basename(source or "plan")
    base = re.sub(r"\.md$", "", base, flags=re.I)
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-._").lower()
    return base or "plan"


def build(raw, source, slug=None, generated_at=""):
    """Plan Markdown to the keyword arguments shell.render takes."""
    plan = parse(raw)
    used = set()

    body = [_meta_html(plan)]
    rows = []
    for sec in plan["sections"]:
        body.append(_section_html(sec, used))
        rows.append({
            "id": sec["id"], "num": sec["num"], "name": sec["name"], "kind": sec["kind"],
            # Step decisions are keyed by step id, so the prompt builder needs the
            # steps that belong to each section. Without this a skipped step is
            # stored but never reaches Claude.
            "steps": [{"id": st["id"], "name": st["name"]} for st in sec["steps"]],
        })

    source_disp = source.replace("\\", "/")
    footer = (
        "Apply the changes directly in %s, then render its review page again with "
        "review-doc and hand over the link. "
        "Everything not mentioned stays as it is. Steps marked DECLINE are dropped from the plan."
        % source_disp
    )

    joined = chr(10).join(p for p in body if p)
    joined = '<div class="plain">' + joined + "</div>"

    return {
        "title": plan["title"],
        "body_html": joined,
        "sections": rows,
        "prompt_spec": {
            "header": 'Review of the plan "%s" (%s):' % (plan["title"], source_disp),
            "footer": footer,
        },
        # Every layout declares the buttons that send it. A plan is reviewed,
        # so it offers a verdict; a screen offers one Send.
        "actions": shell.PLAN_ACTIONS,
        "meta": {
            "slug": slug or slug_for(source),
            "kind": "plan",
            "source": source_disp,
            "generatedAt": generated_at,
        },
    }
