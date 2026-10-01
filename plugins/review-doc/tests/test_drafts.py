# -*- coding: utf-8 -*-
import io
import json
import os
import time
from types import SimpleNamespace

from harness import test, new_home, patch

import drafts


def rec_file(home, slug):
    return os.path.join(home, "drafts", slug + ".json")


@test
def test_first_build_writes_draft_one():
    h = new_home()
    rec = drafts.on_build("a-1", 1000, home=h, now_ms=5000)
    assert rec == {"draft": 1, "firstRendered": 5000, "pending": None}, rec
    on_disk = json.load(io.open(rec_file(h, "a-1"), encoding="utf-8"))
    assert on_disk == rec, on_disk


@test
def test_request_then_older_or_equal_source_does_not_count():
    h = new_home()
    drafts.on_build("a-1", 1000, home=h, now_ms=5000)
    drafts.request("a-1", 1000, home=h)
    assert drafts.on_build("a-1", 1000, home=h)["draft"] == 1
    assert drafts.on_build("a-1", 900, home=h)["draft"] == 1
    assert drafts.load("a-1", home=h)["pending"] == {"sourceMtime": 1000}


@test
def test_request_then_newer_source_counts_once():
    h = new_home()
    drafts.on_build("a-1", 1000, home=h, now_ms=5000)
    drafts.request("a-1", 1000, home=h)
    rec = drafts.on_build("a-1", 2000, home=h)
    assert rec["draft"] == 2 and rec["pending"] is None, rec
    assert drafts.on_build("a-1", 3000, home=h)["draft"] == 2


@test
def test_many_builds_after_one_request_count_once():
    # The plan hook renders on every Write/Edit while Claude revises.
    h = new_home()
    drafts.on_build("p-1", 1000, home=h, now_ms=5000)
    drafts.request("p-1", 1000, home=h)
    for mtime in (1100, 1200, 1300, 1400, 1500):
        drafts.on_build("p-1", mtime, home=h)
    assert drafts.load("p-1", home=h)["draft"] == 2


@test
def test_cancel_then_newer_source_does_not_count():
    h = new_home()
    drafts.on_build("a-1", 1000, home=h, now_ms=5000)
    drafts.request("a-1", 1000, home=h)
    drafts.cancel("a-1", home=h)
    assert drafts.load("a-1", home=h)["pending"] is None
    assert drafts.on_build("a-1", 2000, home=h)["draft"] == 1


@test
def test_request_without_record_creates_one():
    h = new_home()
    rec = drafts.request("old-page", 1000, home=h, now_ms=7000)
    assert rec == {"draft": 1, "firstRendered": 7000, "pending": {"sourceMtime": 1000}}, rec
    assert drafts.on_build("old-page", 2000, home=h)["draft"] == 2


@test
def test_cancel_without_record_is_none_and_writes_nothing():
    h = new_home()
    assert drafts.cancel("nothing", home=h) is None
    assert not os.path.exists(rec_file(h, "nothing"))


@test
def test_corrupt_record_reads_fresh_and_is_rewritten():
    h = new_home()
    os.makedirs(os.path.join(h, "drafts"))
    for junk in ("{not json", "[]", '{"draft": 0, "firstRendered": 1}', '{"draft": "3", "firstRendered": 1}'):
        with io.open(rec_file(h, "bad"), "w", encoding="utf-8", newline="") as fh:
            fh.write(junk)
        assert drafts.load("bad", home=h) is None, junk
        rec = drafts.on_build("bad", 1000, home=h, now_ms=42)
        assert rec == {"draft": 1, "firstRendered": 42, "pending": None}, (junk, rec)
        assert json.load(io.open(rec_file(h, "bad"), encoding="utf-8")) == rec


@test
def test_a_bad_pending_is_dropped_not_fatal():
    h = new_home()
    os.makedirs(os.path.join(h, "drafts"))
    with io.open(rec_file(h, "x"), "w", encoding="utf-8", newline="") as fh:
        fh.write('{"draft": 4, "firstRendered": 1, "pending": {"sourceMtime": "soon"}}')
    assert drafts.load("x", home=h) == {"draft": 4, "firstRendered": 1, "pending": None}


@test
def test_out_of_range_times_are_broken_or_dropped():
    h = new_home()
    os.makedirs(os.path.join(h, "drafts"))
    for bad in (-5, 0, 10 ** 14, 10 ** 30):
        with io.open(rec_file(h, "t"), "w", encoding="utf-8", newline="") as fh:
            fh.write('{"draft": 3, "firstRendered": %d}' % bad)
        assert drafts.load("t", home=h) is None, bad
        rec = drafts.on_build("t", 1000, home=h, now_ms=42)
        assert rec == {"draft": 1, "firstRendered": 42, "pending": None}, rec
        with io.open(rec_file(h, "t"), "w", encoding="utf-8", newline="") as fh:
            fh.write('{"draft": 3, "firstRendered": 7, "pending": {"sourceMtime": %d}}' % bad)
        assert drafts.load("t", home=h) == {"draft": 3, "firstRendered": 7, "pending": None}, bad


@test
def test_a_failed_promoting_save_keeps_the_promoted_number():
    h = new_home()
    drafts.on_build("p", 1000, home=h, now_ms=5)
    drafts.request("p", 1000, home=h)

    def failing(*a, **k):
        raise OSError("disk full")

    with patch(drafts, "_save", failing):
        rec = drafts.on_build("p", 2000, home=h, now_ms=9)
    assert rec == {"draft": 2, "firstRendered": 5, "pending": None}, rec
    on_disk = json.load(io.open(rec_file(h, "p"), encoding="utf-8"))
    assert on_disk["draft"] == 1 and on_disk["pending"] == {"sourceMtime": 1000}, on_disk
    assert drafts.on_build("p", 2000, home=h, now_ms=9)["draft"] == 2


@test
def test_bad_slug_is_refused_and_on_build_fails_soft():
    h = new_home()
    for slug in ("../evil", "a/b", "", "..", "a b"):
        try:
            drafts.request(slug, 1, home=h)
        except ValueError:
            pass
        else:
            raise AssertionError("request accepted %r" % slug)
        rec = drafts.on_build(slug, 1, home=h, now_ms=9)
        assert rec == {"draft": 1, "firstRendered": 9, "pending": None}, rec
    assert not os.path.exists(os.path.join(h, "evil.json"))


@test
def test_prune_keeps_live_pages_and_young_orphans():
    h = new_home()
    now = time.time()
    os.makedirs(os.path.join(h, "pages"))
    for slug in ("live", "young", "old"):
        drafts.on_build(slug, 1, home=h, now_ms=1)
    io.open(os.path.join(h, "pages", "live.html"), "w", encoding="utf-8", newline="").close()
    old = now - (drafts.KEEP_DAYS + 1) * 86400
    os.utime(rec_file(h, "live"), (old, old))
    os.utime(rec_file(h, "old"), (old, old))
    assert drafts.prune(home=h, now=now) == 1
    assert os.path.exists(rec_file(h, "live")), "its page still exists"
    assert os.path.exists(rec_file(h, "young")), "younger than 30 days"
    assert not os.path.exists(rec_file(h, "old"))


@test
def test_prune_without_folder_is_zero():
    assert drafts.prune(home=new_home()) == 0


def stat_with(**kw):
    def fake(path):
        return SimpleNamespace(**kw)
    return fake


@test
def test_created_uses_birthtime_when_there_is_one():
    rec = {"draft": 1, "firstRendered": 1, "pending": None}
    got = drafts.created("x.md", rec, stat=stat_with(st_birthtime=1759327320.5, st_ctime=1.0), nt=False)
    assert got == ("Created", 1759327320500), got


@test
def test_created_uses_ctime_on_windows():
    rec = {"draft": 1, "firstRendered": 1, "pending": None}
    got = drafts.created("x.md", rec, stat=stat_with(st_ctime=1759327320.0), nt=True)
    assert got == ("Created", 1759327320000), got


@test
def test_created_falls_back_to_first_reviewed():
    rec = {"draft": 1, "firstRendered": 1759327320000, "pending": None}
    assert drafts.created("x.md", rec, stat=stat_with(st_ctime=5.0), nt=False) == ("First reviewed", 1759327320000)
    assert drafts.created("x.md", rec, stat=stat_with(st_birthtime=0, st_ctime=5.0), nt=False)[0] == "First reviewed"

    def missing(path):
        raise OSError("gone")
    assert drafts.created("x.md", rec, stat=missing, nt=True) == ("First reviewed", 1759327320000)


@test
def test_fmt_is_day_month_year_hours_minutes_local():
    ms = int(time.mktime((2026, 10, 1, 22, 14, 0, 0, 0, -1)) * 1000)
    assert drafts.fmt(ms) == "01.10.2026 22:14", drafts.fmt(ms)


@test
def test_facts_are_three_rows_in_order():
    ms = int(time.mktime((2026, 10, 1, 22, 14, 0, 0, 0, -1)) * 1000)
    rec = {"draft": 3, "firstRendered": ms, "pending": None}
    got = drafts.facts(rec, os.path.join(new_home(), "missing.md"), ms)
    assert got == [("Draft", "3"), ("First reviewed", "01.10.2026 22:14"),
                   ("Last edited", "01.10.2026 22:14")], got
