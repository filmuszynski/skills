# -*- coding: utf-8 -*-
import io
import json
import os

from harness import test, new_home, use_home, HERE

import paths
import settings


def write_raw(home, text):
    os.makedirs(home, exist_ok=True)
    with io.open(os.path.join(home, "config.json"), "w", encoding="utf-8") as fh:
        fh.write(text)


@test
def test_home_dir_honours_env():
    assert paths.home_dir() == os.environ["REVIEW_DOC_HOME"]


@test
def test_version_reads_plugin_json():
    manifest =os.path.join(os.path.dirname(HERE), ".claude-plugin", "plugin.json")
    with io.open(manifest, encoding="utf-8") as fh:
        want = json.load(fh)["version"]
    assert paths.version() == want, (paths.version(), want)


@test
def test_defaults_when_no_file():
    h = new_home()
    assert settings.load(h) == settings.DEFAULTS


@test
def test_corrupt_json_gives_defaults():
    h = new_home()
    write_raw(h, "{ not json")
    assert settings.load(h) == settings.DEFAULTS


@test
def test_bad_fields_fall_back_one_by_one():
    h = new_home()
    write_raw(h, json.dumps({"stale_hours": 0, "auto_open": "yes", "kinds": {"md": False, "plan": 3}, "junk": 1}))
    got = settings.load(h)
    assert got["stale_hours"] == 96          # out of range -> default
    assert got["auto_open"] is True          # wrong type -> default
    assert got["kinds"]["md"] is False       # valid -> kept
    assert got["kinds"]["plan"] is True      # wrong type -> default
    assert "junk" not in got


@test
def test_save_rewrites_a_broken_file_cleanly():
    h = new_home()
    write_raw(h, "{ not json")
    settings.set_value("stale-hours", "48", h)
    with io.open(os.path.join(h, "config.json"), encoding="utf-8") as fh:
        stored = json.load(fh)
    assert stored["stale_hours"] == 48 and stored["kinds"]["md"] is True


@test
def test_set_value_parses_booleans():
    h = new_home()
    for raw, want in (("off", False), ("on", True), ("0", False), ("TRUE", True)):
        assert settings.set_value("auto-open", raw, h)["auto_open"] is want, raw


@test
def test_set_value_rejects_bad_input_and_keeps_file():
    h = new_home()
    settings.set_value("stale-hours", "48", h)
    for name, raw in (("stale-hours", "0"), ("stale-hours", "721"), ("stale-hours", "abc"),
                      ("md", "maybe"), ("colour", "red")):
        try:
            settings.set_value(name, raw, h)
        except settings.SettingError:
            pass
        else:
            raise AssertionError("accepted %s=%s" % (name, raw))
    assert settings.load(h)["stale_hours"] == 48


@test
def test_reset_restores_defaults():
    h = new_home()
    settings.set_value("md", "off", h)
    assert settings.reset(h) == settings.DEFAULTS
    assert settings.kind_enabled("md", h) is True


@test
def test_cli_show_set_reset():
    use_home(new_home())
    assert settings.main(["set", "choice", "off"]) == 0
    assert settings.kind_enabled("choice") is False
    assert settings.main(["set", "stale-hours", "nope"]) == 2
    assert settings.main(["show"]) == 0
    assert settings.main(["reset"]) == 0
    assert settings.kind_enabled("choice") is True
    assert settings.main(["bogus"]) == 2


@test
def test_save_does_not_depend_on_a_fixed_temp_name():
    """Review fix: two saves shared config.json.tmp; a leftover or concurrent one broke the other."""
    h = new_home()
    os.makedirs(os.path.join(h, "config.json.tmp"))   # squats on the old fixed temp name
    assert settings.set_value("stale-hours", "12", h)["stale_hours"] == 12
    assert settings.load(h)["stale_hours"] == 12


@test
def test_apply_partial_update_saves():
    h = new_home()
    got = settings.apply({"stale_hours": 48, "kinds": {"choice": False}}, h)
    assert got["stale_hours"] == 48 and got["kinds"]["choice"] is False
    assert got["kinds"]["md"] is True and got["auto_open"] is True
    assert settings.load(h) == got


@test
def test_apply_names_the_bad_field_and_writes_nothing():
    h = new_home()
    settings.apply({"stale_hours": 10}, h)
    cases = [
        ({"stale_hours": 0}, "stale_hours"),
        ({"stale_hours": 721}, "stale_hours"),
        ({"stale_hours": True}, "stale_hours"),
        ({"stale_hours": 48.0}, "stale_hours"),
        ({"auto_open": "yes"}, "auto_open"),
        ({"kinds": []}, "kinds"),
        ({"kinds": {"md": 1}}, "kinds.md"),
        # a valid field before a bad one is not saved either
        ({"auto_open": False, "kinds": {"plan": "off"}}, "kinds.plan"),
    ]
    for update, field in cases:
        try:
            settings.apply(update, h)
        except settings.SettingError as exc:
            assert exc.field == field, (update, exc.field)
        else:
            raise AssertionError("accepted %r" % (update,))
    cfg = settings.load(h)
    assert cfg["stale_hours"] == 10 and cfg["auto_open"] is True


@test
def test_apply_rejects_unknown_and_internal_keys():
    h = new_home()
    for update, field in (({"vscode_asked": True}, "vscode_asked"),
                          ({"colour": "red"}, "colour"),
                          ({"kinds": {"pdf": True}}, "kinds.pdf")):
        try:
            settings.apply(update, h)
        except settings.SettingError as exc:
            assert exc.field == field, exc.field
        else:
            raise AssertionError("accepted %r" % (update,))
    try:
        settings.apply(["not", "an", "object"], h)
    except settings.SettingError as exc:
        assert exc.field is None
    else:
        raise AssertionError("accepted a list")
    assert not os.path.exists(os.path.join(h, "config.json"))


@test
def test_reset_keeps_the_extension_answer():
    h = new_home()
    cfg = settings.load(h)
    cfg["vscode_asked"] = True
    cfg["stale_hours"] = 5
    settings.save(cfg, h)
    after = settings.reset(h)
    assert after["stale_hours"] == 96 and after["vscode_asked"] is True, after
    assert settings.load(h)["vscode_asked"] is True
