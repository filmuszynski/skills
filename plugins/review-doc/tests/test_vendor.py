# -*- coding: utf-8 -*-
import os
import subprocess
import sys

from harness import test, PRESENTER


@test
def test_markdown_is_the_vendored_copy():
    import layout_common
    import markdown
    want = os.path.join(PRESENTER, "vendor", "markdown")
    assert os.path.normcase(os.path.dirname(markdown.__file__)) == os.path.normcase(want), markdown.__file__
    assert all(e.startswith("markdown.extensions.") for e in layout_common.MD_EXTENSIONS), layout_common.MD_EXTENSIONS


@test
def test_renders_in_an_isolated_interpreter():
    """-I drops the user site-packages, so an installed Markdown cannot help."""
    code = ("import sys; sys.path.insert(0, %r); import layout_common as c; "
            "print(c._md('| a |\\n|---|\\n| 1 |'))" % PRESENTER)
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "<table>" in out.stdout, out.stdout


@test
def test_vendored_license_is_present():
    assert os.path.isfile(os.path.join(PRESENTER, "vendor", "markdown", "LICENSE.md"))
