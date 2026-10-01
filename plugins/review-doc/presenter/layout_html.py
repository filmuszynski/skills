# -*- coding: utf-8 -*-
"""HTML pages (1.2): the reviewed page sits in a frame on its own origin.

The page is the usual shell around one <iframe>. shell_html.js points the frame
at http://<slug>.localhost:<review port + 100>/<entry>, where the review server's
frame listener serves the file's folder (server/frame_server.py, ADR 0016).

Phase 1 builds the frame and records the target in meta. The width group, the
Use | Comment | Edit text switch, marks and the answer arrive in later phases.
"""
from __future__ import unicode_literals

import html as _html
import os
import re

import layout_doc
import shell

_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title\s*>", re.I | re.S)


def _page_words(text):
    return re.sub(r"\bdocument\b", "page", re.sub(r"\bdocuments\b", "pages", text))


# The document page's two verdicts, word for word, with "document" read as "page".
ACTIONS = [dict(a, **{k: _page_words(a[k]) for k in ("line", "bare", "tip") if k in a})
           for a in layout_doc.ACTIONS]


def page_title(text, fallback):
    """The page's <title>, whitespace collapsed, else the fallback."""
    m = _TITLE_RE.search(text or "")
    title = re.sub(r"\s+", " ", _html.unescape(m.group(1))).strip() if m else ""
    return title or fallback


def build(raw, source, slug, generated_at=""):
    """An HTML file's text and path to the keyword arguments shell.render takes."""
    source_disp = source.replace("\\", "/")
    root, entry = os.path.dirname(source_disp), os.path.basename(source_disp)
    title = page_title(raw, entry)
    body = ('<div class="html-stage"><iframe id="review-frame" title="%s" '
            'referrerpolicy="no-referrer"></iframe></div>' % shell._esc(title))
    footer = (
        "Apply the changes in %s, or in whatever generates it, then render its review "
        "page again with review-doc and hand over the link. "
        "Everything not mentioned stays as it is." % source_disp
    )
    return {
        "title": title,
        "body_html": body,
        "sections": [],
        "prompt_spec": {
            "header": 'Review of the HTML page "%s" (%s):' % (title, source_disp),
            "footer": footer,
            "generalLabel": "Whole page",
        },
        "actions": ACTIONS,
        "meta": {
            "slug": slug,
            "kind": "html",
            "source": source_disp,
            "generatedAt": generated_at,
            "target": {"type": "file", "root": root, "entry": entry},
        },
        "general_placeholder": "A note on the whole page, optional",
        "scripts": ["shell_html.js"],
    }
