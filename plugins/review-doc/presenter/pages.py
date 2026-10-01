# -*- coding: utf-8 -*-
"""Page housekeeping in ~/.review-doc/pages/."""
import io
import json
import os
import re
import time

import paths
import settings


def prune(home=None, now=None, hours=None):
    """Delete pages/*.html older than the window. Nothing else, no subfolders."""
    home = home or paths.home_dir()
    hours = hours if hours is not None else settings.load(home)["stale_hours"]
    cutoff = (now if now is not None else time.time()) - hours * 3600
    d = os.path.join(home, "pages")
    gone = 0
    try:
        names = os.listdir(d)
    except OSError:
        return 0
    for n in names:
        if not n.lower().endswith(".html"):
            continue
        p = os.path.join(d, n)
        try:
            if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                os.remove(p)
                gone += 1
        except OSError:
            pass  # in use or already gone: the next run gets it
    return gone


# shell.PAGE writes the data as `window.PRESENTER_DATA = <json>;` followed by a newline
# and </script>. The JSON never contains "</" (shell escapes it), so the first
# ";\n</script>" ends it.
_DATA_RE = re.compile(r"window\.PRESENTER_DATA = (.*?);\n</script>", re.S)


def read_meta(page_path):
    """The meta object of a rendered page, or None if the file is missing or not a page."""
    try:
        with io.open(page_path, encoding="utf-8") as fh:
            html = fh.read()
    except (OSError, ValueError):
        return None
    m = _DATA_RE.search(html)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return None
    meta = data.get("meta") if isinstance(data, dict) else None
    return meta if isinstance(meta, dict) else None
