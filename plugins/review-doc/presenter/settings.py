# -*- coding: utf-8 -*-
"""Settings in ~/.review-doc/config.json, shared by the page, the server and the CLI.

    python presenter/settings.py show
    python presenter/settings.py set stale-hours 48
    python presenter/settings.py reset
"""
from __future__ import print_function

import copy
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

DEFAULTS = {
    "stale_hours": 96,
    "auto_open": True,
    "show_tips": True,
    "kinds": {"md": True, "html": True, "plan": True, "choice": True},
    "vscode_asked": False,
}
CLI_NAMES = {
    "stale-hours": ("stale_hours",),
    "auto-open": ("auto_open",),
    "tooltips": ("show_tips",),
    "md": ("kinds", "md"),
    "html": ("kinds", "html"),
    "plan": ("kinds", "plan"),
    "choice": ("kinds", "choice"),
}
TRUE, FALSE = {"on", "true", "1", "yes"}, {"off", "false", "0", "no"}


class SettingError(ValueError):
    def __init__(self, message, field=None):
        ValueError.__init__(self, message)
        self.field = field


def _valid(key_path, value):
    if key_path == ("stale_hours",):
        return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 720
    return isinstance(value, bool)


def _clean(raw):
    """Defaults, overlaid with every stored value that is valid. Anything else is dropped."""
    cfg = copy.deepcopy(DEFAULTS)
    if not isinstance(raw, dict):
        return cfg
    for key in ("stale_hours", "auto_open", "show_tips", "vscode_asked"):
        if key in raw and _valid((key,), raw[key]):
            cfg[key] = raw[key]
    kinds = raw.get("kinds")
    if isinstance(kinds, dict):
        for k in DEFAULTS["kinds"]:
            if k in kinds and isinstance(kinds[k], bool):
                cfg["kinds"][k] = kinds[k]
    return cfg


def load(home=None):
    try:
        with io.open(paths.config_path(home), encoding="utf-8") as fh:
            return _clean(json.load(fh))
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULTS)


def save(cfg, home=None):
    clean = _clean(cfg)
    path = paths.config_path(home)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # A unique temp name per save: two saves at once, or a leftover, cannot collide.
    fd, tmp = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=os.path.dirname(path))
    os.close(fd)
    try:
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(clean, fh, indent=2)
            fh.write("\n")
        paths.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return clean


def _parse(key_path, raw):
    if key_path == ("stale_hours",):
        try:
            value = int(str(raw).strip())
        except ValueError:
            raise SettingError("stale-hours must be a whole number from 1 to 720, got %r" % raw)
        if not 1 <= value <= 720:
            raise SettingError("stale-hours must be from 1 to 720, got %d" % value)
        return value
    low = str(raw).strip().lower()
    if low in TRUE:
        return True
    if low in FALSE:
        return False
    raise SettingError("expected on or off, got %r" % raw)


def set_value(cli_name, raw, home=None):
    if cli_name not in CLI_NAMES:
        raise SettingError("unknown setting %r; one of: %s" % (cli_name, ", ".join(CLI_NAMES)))
    key_path = CLI_NAMES[cli_name]
    value = _parse(key_path, raw)
    cfg = load(home)
    target = cfg
    for k in key_path[:-1]:
        target = target[k]
    target[key_path[-1]] = value
    return save(cfg, home)


def reset(home=None):
    """The seven user settings back to their defaults. Whether the extension was
    offered is not a setting, so the offer is not repeated after a reset."""
    fresh = copy.deepcopy(DEFAULTS)
    fresh["vscode_asked"] = load(home)["vscode_asked"]
    return save(fresh, home)


def apply(update, home=None):
    """Strict partial update, for the server. Every field present must be valid, or
    nothing is saved; vscode_asked is internal and cannot be set this way."""
    if not isinstance(update, dict):
        raise SettingError("expected a JSON object", None)
    cfg = load(home)
    for key, value in update.items():
        if key == "stale_hours":
            if not _valid((key,), value):
                raise SettingError("stale_hours must be a whole number from 1 to 720", key)
            cfg[key] = value
        elif key in ("auto_open", "show_tips"):
            if not isinstance(value, bool):
                raise SettingError("%s must be true or false" % key, key)
            cfg[key] = value
        elif key == "kinds":
            if not isinstance(value, dict):
                raise SettingError("kinds must be an object", key)
            for k, v in value.items():
                if k not in DEFAULTS["kinds"]:
                    raise SettingError("unknown kind %r" % k, "kinds." + str(k))
                if not isinstance(v, bool):
                    raise SettingError("kinds.%s must be true or false" % k, "kinds." + k)
                cfg["kinds"][k] = v
        else:
            raise SettingError("unknown or read-only setting %r" % key, str(key))
    return save(cfg, home)


def kind_enabled(cli_name, home=None):
    return bool(load(home)["kinds"][cli_name])


def _show(cfg):
    def onoff(b):
        return "on" if b else "off"
    rows = [("stale-hours", str(cfg["stale_hours"])), ("auto-open", onoff(cfg["auto_open"])),
            ("tooltips", onoff(cfg["show_tips"]))]
    rows += [(k, onoff(cfg["kinds"][k])) for k in ("md", "html", "plan", "choice")]
    return "\n".join("%-12s %s" % r for r in rows)


def main(argv):
    try:
        if argv[:1] == ["show"] and len(argv) == 1:
            print(_show(load()))
            print("\nfile: %s" % paths.config_path())
            return 0
        if argv[:1] == ["set"] and len(argv) == 3:
            print(_show(set_value(argv[1], argv[2])))
            return 0
        if argv[:1] == ["reset"] and len(argv) == 1:
            print(_show(reset()))
            return 0
    except SettingError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    print("usage: settings.py show | set <name> <value> | reset\nnames: " + ", ".join(CLI_NAMES), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
