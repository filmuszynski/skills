# -*- coding: utf-8 -*-
"""Shared test harness: the @test registry, fixtures, and a home folder that is never the real one."""
from __future__ import print_function

import contextlib
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PRESENTER = os.path.join(os.path.dirname(HERE), "presenter")
TMP = os.path.join(HERE, ".tmp")
sys.path.insert(0, PRESENTER)

os.makedirs(TMP, exist_ok=True)
# Set before any presenter module is imported: nothing in a test run may read or
# prune the real ~/.review-doc.
os.environ["REVIEW_DOC_HOME"] = os.path.join(TMP, "home-default")
DEFAULT_HOME = os.environ["REVIEW_DOC_HOME"]
# Nothing in a test run may start a real server on 7777-7787 or open a browser. The
# few tests that need either switch these off with env(), which restores them.
os.environ["REVIEW_DOC_NO_SERVER"] = "1"
os.environ["REVIEW_DOC_NO_OPEN"] = "1"
os.environ["REVIEW_DOC_PORTS"] = "27777-27787"
PORTS = range(27777, 27788)
# Deciding the extension offer reads the VS Code extensions folder; never the real one.
os.environ["VSCODE_EXTENSIONS"] = os.path.join(TMP, "no-extensions")
os.makedirs(os.environ["VSCODE_EXTENSIONS"], exist_ok=True)

RESULTS = []


def test(fn):
    RESULTS.append(fn)
    return fn


def fixture(name):
    # Plain utf-8, as the ported run.py did: the BOM fixture test needs the BOM kept.
    with io.open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as fh:
        return fh.read()


def new_home():
    """A fresh, empty home folder for one test."""
    return tempfile.mkdtemp(prefix="home-", dir=TMP)


def use_home(h):
    """Point REVIEW_DOC_HOME at h for the rest of this test; run.py resets it after each test."""
    os.environ["REVIEW_DOC_HOME"] = h
    return h


@contextlib.contextmanager
def env(**changes):
    """Set (or, with None, unset) environment variables for one block."""
    saved = {k: os.environ.get(k) for k in changes}
    for k, v in changes.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextlib.contextmanager
def patch(obj, name, value):
    """Replace obj.name for one block."""
    saved = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield value
    finally:
        setattr(obj, name, saved)
