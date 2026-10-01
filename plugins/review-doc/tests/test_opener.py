# -*- coding: utf-8 -*-
import io
import json
import os
import shutil
import subprocess

from harness import test, HERE

import paths

OPENER = os.path.join(os.path.dirname(HERE), "vscode-opener")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))


def accept(urls):
    node = shutil.which("node")
    assert node, "node is needed for the opener tests"
    script = ("const a = require(process.argv[1]).acceptable;"
              "console.log(JSON.stringify(JSON.parse(process.argv[2]).map(a)));")
    r = subprocess.run([node, "-e", script, os.path.join(OPENER, "accept.js"), json.dumps(urls)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@test
def test_opener_accepts_only_review_pages():
    good = ["http://127.0.0.1:7777/review/notes-a1b2c3.html",
            "http://localhost:7781/review/plan_x.v2-000000.html"]
    bad = ["https://127.0.0.1:7777/review/a.html",
           "http://example.com:7777/review/a.html",
           "http://127.0.0.1:7777@evil.example/review/a.html",
           "http://user:pw@127.0.0.1:7777/review/a.html",
           "http://127.0.0.1/review/a.html",
           "http://127.0.0.1:7777/api/settings",
           "http://127.0.0.1:7777/review/../api/settings",
           "http://127.0.0.1:7777/review/a.html?x=1",
           "http://127.0.0.1:7777/review/a.html#top",
           "http://127.0.0.1:7777/review/sub/a.html",
           "http://[::1]:7777/review/a.html",
           "file:///tmp/a.html",
           "javascript:alert(1)",
           "",
           "not a url"]
    got = accept(good + bad)
    assert got[:2] == good, got[:2]
    assert got[2:] == [None] * len(bad), list(zip(bad, got[2:]))


@test
def test_opener_manifest_is_renamed_and_follows_the_plugin():
    with io.open(os.path.join(OPENER, "package.json"), encoding="utf-8") as fh:
        pkg = json.load(fh)
    assert (pkg["publisher"], pkg["name"]) == ("filmuszynski", "review-doc-opener"), pkg
    assert pkg["license"] == "MIT" and "private" not in pkg
    assert pkg["version"] == paths.version().split("-")[0], (pkg["version"], paths.version())
    assert pkg["activationEvents"] == ["onUri"]
    lic = io.open(os.path.join(OPENER, "LICENSE"), encoding="utf-8").read()
    assert lic == io.open(os.path.join(REPO, "LICENSE"), encoding="utf-8").read()
    ext = io.open(os.path.join(OPENER, "extension.js"), encoding="utf-8").read()
    assert 'require("./accept")' in ext and "showWarningMessage" not in ext
    ignore = io.open(os.path.join(OPENER, ".vscodeignore"), encoding="utf-8").read()
    assert "accept.js" not in ignore
