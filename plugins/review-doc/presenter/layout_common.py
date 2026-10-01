# -*- coding: utf-8 -*-
"""The few helpers every layout shares.

They live here rather than in `layout_plan` because `layout_tables` needs them
too, and `layout_plan` imports `layout_tables`. `layout_plan` re-exports them,
so existing `from layout_plan import _md` callers keep working.
"""
from __future__ import unicode_literals

import hashlib
import os
import re
import sys

# The vendored copy comes first, so a user's own (maybe different) Markdown never
# changes how pages render, and a machine without one still works.
_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

import markdown  # noqa: E402

# Module paths, not short names: short names resolve through package entry points,
# and a vendored copy has none.
MD_EXTENSIONS = ["markdown.extensions.tables", "markdown.extensions.sane_lists",
                 "markdown.extensions.fenced_code"]


def _hash(text, prefix):
    norm = re.sub(r"\s+", " ", text or "").strip().lower()
    return prefix + hashlib.sha1(norm.encode("utf-8")).hexdigest()[:8]


RE_THEAD = re.compile(r"<thead>\s*<tr>(.*?)</tr>\s*</thead>", re.S)
RE_HEAD_CELL = re.compile(r"<th\b[^>]*>(.*?)</th>", re.S)


def _mark_blank_heads(html):
    """Markdown needs a header row, so a key/value table written as | | | gets
    an empty shaded bar. Its header stays in the DOM, because the table toolbar
    and the serialiser count columns from it, and is only hidden."""
    def one(m):
        cells = RE_HEAD_CELL.findall(m.group(1))
        if cells and all(not re.sub(r"<[^>]+>|&nbsp;|\s", "", c) for c in cells):
            return m.group(0).replace("<thead>", '<thead class="blank">', 1)
        return m.group(0)
    return RE_THEAD.sub(one, html)


def _md(text):
    if not text or not text.strip():
        return ""
    return _mark_blank_heads(markdown.markdown(text, extensions=MD_EXTENSIONS))


def _mask_pre(html):
    """Take <pre> blocks out of reach so nothing inside them becomes editable."""
    blocks = []

    def grab(m):
        blocks.append(m.group(0))
        return "\x00PRE%d\x00" % (len(blocks) - 1)

    return re.sub(r"<pre\b.*?</pre>", grab, html, flags=re.S), blocks


def _unmask_pre(html, blocks):
    for i, block in enumerate(blocks):
        html = html.replace("\x00PRE%d\x00" % i, block)
    return html


def _esc(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))
