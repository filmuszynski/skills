"""The encoding of an HTML file, found the way a browser finds it: a byte order
mark first, then a <meta> charset in the first 1024 bytes, else UTF-8.

Used by the renderer (the page's <title>) and by the frame listener (the page as
served), so the review page and the reviewed page agree."""

import codecs
import re

_BOMS = ((codecs.BOM_UTF8, "utf-8"),
         (codecs.BOM_UTF16_LE, "utf-16-le"),
         (codecs.BOM_UTF16_BE, "utf-16-be"))
# <meta charset="x"> and <meta http-equiv="Content-Type" content="text/html; charset=x">.
_META_RE = re.compile(r"""<meta\b[^>]*?charset\s*=\s*["']?\s*([A-Za-z0-9._:-]+)""", re.I)
PRESCAN = 1024


def sniff(data):
    """(encoding, bom length) for an HTML file's bytes."""
    for bom, name in _BOMS:
        if data.startswith(bom):
            return name, len(bom)
    m = _META_RE.search(data[:PRESCAN].decode("ascii", "replace"))
    if m:
        try:
            name = codecs.lookup(m.group(1)).name
        except LookupError:
            return "utf-8", 0
        # A declared UTF-16 without a BOM is read as UTF-8, as the HTML standard says.
        if not name.startswith("utf-16"):
            return name, 0
    return "utf-8", 0


def decode(data):
    """(text without the BOM, encoding, bom length)."""
    enc, bom = sniff(data)
    return data[bom:].decode(enc, "replace"), enc, bom
