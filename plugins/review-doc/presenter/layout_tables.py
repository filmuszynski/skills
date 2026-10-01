# -*- coding: utf-8 -*-
"""Identity and source fidelity for pipe tables on a review page.

Two passes meet here. The rendered HTML knows the structure, the Markdown knows
what each cell really said, `[Die Transkription](https://…)` rather than the
link text. python-markdown emits one <table> per pipe-table block in source
order, rows and cells one to one, so the two are zipped positionally. When the
counts disagree (a raw-HTML <table> in the section) nothing is stamped and the
table simply gets no toolbar, which is the documented out-of-scope behaviour.

Spec: docs/superpowers/specs/2026-09-11-presenter-table-editing-design.md
"""
from __future__ import unicode_literals

import re

import layout_common as common

RE_FENCE = re.compile(r"^\s*(```|~~~)")
RE_DELIM = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
RE_TABLE = re.compile(r"<table>(.*?)</table>", re.S)


def split_row(line):
    """One pipe-table line to its cells' Markdown, split on unescaped pipes."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells, cur, i = [], "", 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            cur += s[i:i + 2]
            i += 2
            continue
        if ch == "|":
            cells.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    cells.append(cur.strip())
    return cells


RE_LIST_ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s")
RE_ATX = re.compile(r"^ {0,3}#{1,6}(\s|$)")


def _indent(s):
    return len(s.expandtabs(4)) - len(s.expandtabs(4).lstrip(" "))


def _starts_block(lines, i):
    """python-markdown only reads a table that opens a block: after a blank
    line, at the start, or straight under a heading. A header line glued to a
    paragraph or a list item is that paragraph's text."""
    return i == 0 or not lines[i - 1].strip() or bool(RE_ATX.match(lines[i - 1]))


def _indented_code(lines, i):
    """Four spaces past the enclosing list item's content is code.

    Under a list item the first four spaces are the item's continuation, so a
    table indented by four there is a table, and only eight makes it code.
    """
    ind = _indent(lines[i])
    k = i - 1
    while k >= 0 and (not lines[k].strip() or _indent(lines[k]) >= ind):
        k -= 1
    base = 0
    if k >= 0 and RE_LIST_ITEM.match(lines[k]):
        base = _indent(lines[k]) + 4
    return ind - base >= 4


def find_pipe_tables(md):
    """Every pipe table python-markdown will render, in source order.

    It has to agree with the renderer exactly: `stamp_tables` gives up when the
    counts differ, and the section's real table then silently has no toolbar.
    So a heading underline (`Kosten | Nutzen` over `---`, a delimiter row with
    fewer cells than the header) and a table in indented code do not count.
    """
    lines = (md or "").split("\n")
    out, in_fence, i = [], False, 0
    while i < len(lines):
        line = lines[i]
        if RE_FENCE.match(line):
            in_fence = not in_fence
            i += 1
            continue
        if (not in_fence and "|" in line and i + 1 < len(lines)
                and "-" in lines[i + 1] and RE_DELIM.match(lines[i + 1])
                and _starts_block(lines, i) and not _indented_code(lines, i)
                and len(split_row(lines[i + 1])) == len(split_row(line))):
            head = split_row(line)
            align = lines[i + 1].strip()
            rows, j = [], i + 2
            while j < len(lines) and lines[j].strip() and "|" in lines[j]:
                rows.append(split_row(lines[j]))
                j += 1
            out.append({"head": head, "align": align, "rows": rows})
            i = j
            continue
        i += 1
    return out


def _unique(base, used):
    eid, n = base, 1
    while eid in used:
        n += 1
        eid = "%s-%d" % (base, n)
    used.add(eid)
    return eid


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


RE_CELL = re.compile(r"<(td|th)\b([^>]*)>(.*?)</\1>", re.S)


def _renders_as(md_cell, cell_html):
    """Does this cell source render to the text the page actually shows?

    The zip is positional, so anything python-markdown reads differently from
    `split_row` (a pipe inside a code span, a row line without pipes, a fence
    inside a fence) shifts the pairing. A cell whose source does not render to
    its own text gets no `data-md`, and the serialiser rebuilds it from the DOM
    instead of writing someone else's Markdown into the customer's table.
    """
    return _text(common._md(md_cell)) == _text(cell_html)


def _stamp_one(whole, inner, src, sec_id, used):
    md_rows = [src["head"]] + src["rows"]
    head_html = re.search(r"<tr>(.*?)</tr>", inner, re.S)
    head_cells = RE_CELL.findall(head_html.group(1)) if head_html else []
    if len(head_cells) != len(src["head"]) or not all(
            _renders_as(md, c[2]) for md, c in zip(src["head"], head_cells)):
        # The header itself does not line up: this is not the table we think
        # it is. No ids, no toolbar; the cells stay rewritable as text.
        return whole

    head_text = " | ".join(src["head"])
    first = " | ".join(src["rows"][0]) if src["rows"] else ""
    tid = _unique(common._hash(sec_id + "|table|" + head_text + "|" + first, "tb"), used)
    row_ids = set()
    counter = [0]

    def row(m):
        k = counter[0]
        counter[0] += 1
        md_cells = md_rows[k] if k < len(md_rows) else None
        col = [0]

        def cell(cm):
            i = col[0]
            col[0] += 1
            tag, attrs, body = cm.group(1), cm.group(2), cm.group(3)
            md_attr = ""
            if md_cells is not None and i < len(md_cells) and _renders_as(md_cells[i], body):
                md_attr = ' data-md="%s"' % common._esc(md_cells[i])
            return '<%s data-col-id="c%d"%s%s>%s</%s>' % (tag, i, md_attr, attrs, body, tag)

        if md_cells is None and not _text(m.group(1)):
            # python-markdown gives a header-only table an empty body row.
            # It has no source, so it is not an original row to keep.
            return ""
        body = RE_CELL.sub(cell, m.group(1))
        attrs = ""
        if k > 0:
            attrs = ' data-row-id="%s"' % _unique(common._hash(tid + "|" + _text(body), "r"), row_ids)
        return "<tr%s>%s</tr>" % (attrs, body)

    inner = re.sub(r"<tr>(.*?)</tr>", row, inner, flags=re.S)
    return '<table data-table-id="%s" data-md-align="%s">%s</table>' % (
        tid, common._esc(src["align"]), inner)


def stamp_tables(html, md, sec_id, used):
    """Stamp ids and source onto every rendered pipe table in one block."""
    html, pre = common._mask_pre(html)
    found = RE_TABLE.findall(html)
    src = find_pipe_tables(md)
    if not found or len(found) != len(src):
        return common._unmask_pre(html, pre)
    it = iter(src)
    html = RE_TABLE.sub(lambda m: _stamp_one(m.group(0), m.group(1), next(it), sec_id, used), html)
    return common._unmask_pre(html, pre)
