# -*- coding: utf-8 -*-
"""Retake the README screenshots.

    python docs/screenshots/make.py

Renders the demo into a scratch home on its own ports (never the real ~/.review-doc),
then drives headless Chrome through capture.mjs. Needs Chrome and Node 22+. Set CHROME
to the browser's path if it is not in the usual place.
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PRESENTER = os.path.join(REPO, "plugins", "review-doc", "presenter")
WORK = os.path.join(HERE, ".work")


def render(kind, src, env):
    r = subprocess.run([sys.executable, os.path.join(PRESENTER, "build_screen.py"), kind, src],
                       env=env, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        sys.exit("render failed: %s %s" % (r.stdout, r.stderr))
    res = json.loads(r.stdout.strip().splitlines()[-1])
    if not res.get("server"):
        sys.exit("the scratch server did not start: %s" % res.get("serverNote"))
    return res["url"]


def main():
    shutil.rmtree(WORK, ignore_errors=True)
    demo = os.path.join(WORK, "demo")
    shutil.copytree(os.path.join(HERE, "demo"), demo)
    env = dict(os.environ, REVIEW_DOC_HOME=os.path.join(WORK, "home"),
               REVIEW_DOC_PORTS="27790-27799", REVIEW_DOC_NO_OPEN="1",
               PYTHONIOENCODING="utf-8")
    env.pop("REVIEW_DOC_NO_SERVER", None)
    shots = {
        "doc": render("doc", os.path.join(demo, "field-notes.md"), env),
        "plan": render("plan", os.path.join(demo, "plan.md"), env),
        "choice": render("screen", os.path.join(demo, "choice.md"), env),
        "docSource": os.path.join(demo, "field-notes.md"),
        "out": HERE,
    }
    try:
        subprocess.run(["node", os.path.join(HERE, "capture.mjs"), json.dumps(shots)],
                       check=True, timeout=300)
    finally:
        sys.path.insert(0, PRESENTER)
        os.environ.update(REVIEW_DOC_HOME=env["REVIEW_DOC_HOME"])
        import launch
        info = launch.read_info()
        if info:
            launch.stop(info["port"])


if __name__ == "__main__":
    main()
