# -*- coding: utf-8 -*-
import io
import os

from harness import test, new_home

import shell


@test
def test_page_write_is_atomic():
    """Review fix: a write that fails half way must leave the old page intact, never a half page."""
    h = new_home()
    target = os.path.join(h, "page.html")
    shell.write(target, "<html>old</html>")
    real_open = shell.io.open

    class Boom(object):
        def __init__(self, fh):
            self.fh = fh
        def __enter__(self):
            return self
        def __exit__(self, *a):
            self.fh.close()
        def write(self, _):
            raise OSError("disk full")

    shell.io.open = lambda *a, **k: Boom(real_open(*a, **k))
    try:
        try:
            shell.write(target, "<html>new</html>")
        except OSError:
            pass
    finally:
        shell.io.open = real_open
    assert io.open(target, encoding="utf-8").read() == "<html>old</html>"
    assert [n for n in os.listdir(h) if n != "page.html"] == [], os.listdir(h)
