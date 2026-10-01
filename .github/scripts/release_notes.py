# -*- coding: utf-8 -*-
"""Release notes for a tag, from CHANGELOG.md. Refuses a tag that is not
v<plugin version>, and a version the CHANGELOG has no section for.

    python .github/scripts/release_notes.py v1.0.0 > notes.md
"""
import io
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def section(changelog, version):
    m = re.search(r"^## \[%s\][^\n]*\n(.*?)(?=^## \[|^\[|\Z)" % re.escape(version),
                  changelog, re.S | re.M)
    if not m or not m.group(1).strip():
        raise ValueError("CHANGELOG.md has no section for %s" % version)
    return m.group(1).strip()


def main(argv, version=None, changelog=None):
    if len(argv) != 1:
        print("usage: release_notes.py v<version>", file=sys.stderr)
        return 1
    if version is None:
        with io.open(os.path.join(REPO, "plugins", "review-doc", ".claude-plugin", "plugin.json"),
                     encoding="utf-8") as fh:
            version = json.load(fh)["version"]
    if changelog is None:
        with io.open(os.path.join(REPO, "CHANGELOG.md"), encoding="utf-8") as fh:
            changelog = fh.read()
    if argv[0] != "v" + version:
        print("tag %s does not match plugin.json version %s" % (argv[0], version), file=sys.stderr)
        return 1
    try:
        print(section(changelog, version))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
