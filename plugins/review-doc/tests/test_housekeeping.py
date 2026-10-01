# -*- coding: utf-8 -*-
import io
import os
import time

from harness import test, new_home
from serverkit import serving, review_server


def page(h, name, age_hours):
    d = os.path.join(h, "pages")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with io.open(p, "w", encoding="utf-8") as fh:
        fh.write("<html></html>")
    t = time.time() - age_hours * 3600
    os.utime(p, (t, t))
    return p


def wait_for(cond, seconds=3.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


@test
def test_start_prunes_old_pages():
    h = new_home()
    old, fresh = page(h, "old-000000.html", 200), page(h, "fresh-000000.html", 1)
    with serving(h):
        assert not os.path.exists(old) and os.path.exists(fresh)


@test
def test_prunes_every_interval():
    h = new_home()
    with serving(h, prune_seconds=0.2, tick=0.05):
        old = page(h, "later-000000.html", 200)
        assert wait_for(lambda: not os.path.exists(old)), "hourly prune did not run"


@test
def test_idle_server_exits_and_cleans_up():
    h = new_home()
    with serving(h, idle_seconds=0.3, tick=0.05) as srv:
        assert wait_for(lambda: not srv.thread.is_alive(), 5), "still serving after idle window"
        assert not os.path.exists(srv.info_path)
        again = review_server.Lock(os.path.join(h, "server.lock"))
        assert again.acquire(0), "lock released on idle exit"
        again.release()
    assert "idle" in io.open(os.path.join(h, "server.log"), encoding="utf-8").read()


@test
def test_big_log_is_started_afresh():
    h = new_home()
    with io.open(os.path.join(h, "server.log"), "w", encoding="utf-8") as fh:
        fh.write("x" * (2 * 1000 * 1000))
    with serving(h):
        assert os.path.getsize(os.path.join(h, "server.log")) < 1000


@test
def test_page_prune_also_prunes_orphan_records():
    import drafts
    import pages
    h = new_home()
    drafts.on_build("orphan", 1, home=h, now_ms=1)
    old = time.time() - (drafts.KEEP_DAYS + 1) * 86400
    os.utime(os.path.join(h, "drafts", "orphan.json"), (old, old))
    pages.prune(home=h, hours=96)
    assert not os.path.exists(os.path.join(h, "drafts", "orphan.json"))
