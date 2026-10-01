# -*- coding: utf-8 -*-
"""Where review-doc keeps things, and which version it is."""
import io
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def home_dir():
    return os.environ.get("REVIEW_DOC_HOME") or os.path.join(os.path.expanduser("~"), ".review-doc")


def pages_dir(home=None):
    d = os.path.join(home or home_dir(), "pages")
    os.makedirs(d, exist_ok=True)
    return d


def config_path(home=None):
    return os.path.join(home or home_dir(), "config.json")


def plugin_root():
    return os.path.dirname(HERE)


def version():
    try:
        with io.open(os.path.join(plugin_root(), ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            return str(json.load(fh)["version"])
    except (OSError, ValueError, KeyError):
        return "0.0.0"


def replace(src, dst, tries=40, pause=0.05):
    """os.replace, waiting out a reader. On Windows the rename is refused while any
    process has dst open (the server reads pages, config.json and server.json), so a
    writer retries for up to two seconds before giving up."""
    for attempt in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(pause)
