import threading

from jobfinder import collector
from jobfinder.collector import collect
from jobfinder.db import get_setting, last_runs, set_setting
from jobfinder.http import SourceBlocked, SourceError
from jobfinder.sources.base import ParseError, Source
from tests.conftest import mk


class FakeClient:
    requests = 3

    def close(self):
        self.closed = True


class Fixed(Source):
    lang = "en"
    full_listing = True
    method = "test"

    def __init__(self, name, jobs):
        self.name = name
        self.jobs = jobs

    def parse_item(self, item):
        return None

    def fetch(self, client, known, wants, settings):
        return list(self.jobs)


class Raising(Fixed):
    def __init__(self, name, exc):
        super().__init__(name, [])
        self.exc = exc

    def fetch(self, client, known, wants, settings):
        raise self.exc


def run(conn, sources, **kw):
    return collect(conn, sources=sources, client_factory=FakeClient, **kw)


def test_failing_source_does_not_stop_others(conn):
    res = run(conn, {"bad": Raising("bad", ParseError("no __NEXT_DATA__")),
                     "good": Fixed("good", [mk(source="good")])})
    assert [r.ok for r in res] == [False, True]
    assert "формат страницы изменился" in last_runs(conn)["bad"]["error"]
    assert res[1].fetched == 1 and res[1].new == 1 and res[1].requests == 3


def test_blocked_source_message(conn):
    res = run(conn, {"b": Raising("b", SourceBlocked(429))})
    assert "429" in res[0].error and not res[0].ok


def test_source_error_and_empty_message(conn):
    res = run(conn, {"a": Raising("a", SourceError("boom")), "b": Raising("b", RuntimeError())})
    assert res[0].error == "boom"
    assert res[1].error == "RuntimeError"


def test_job_without_title_skipped(conn):
    res = run(conn, {"s": Fixed("s", [mk(title=""), mk(source_id="2", url=""), mk(source_id="3")])})
    assert res[0].skipped == 2 and res[0].fetched == 3 and res[0].new == 1
    assert conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0] == 1


def test_hidden_jobs_stored_with_reason(conn):
    run(conn, {"s1": Fixed("s1", [mk(location_raw="USA Only")])})
    row = conn.execute("SELECT hidden_reason FROM jobs").fetchone()
    assert row["hidden_reason"] == "restricted"


def test_disabled_source_not_run(conn):
    set_setting(conn, "disabled_sources", ["good"])
    res = run(conn, {"good": Fixed("good", []), "other": Fixed("other", [])})
    assert [r.source for r in res] == ["other"]
    assert "good" not in last_runs(conn)


def test_only_runs_disabled_named_source(conn):
    set_setting(conn, "disabled_sources", ["good"])
    res = run(conn, {"good": Fixed("good", []), "other": Fixed("other", [])}, only="good")
    assert [r.source for r in res] == ["good"]


def test_wants_passed_to_source(conn):
    seen = {}

    class Rec(Fixed):
        def fetch(self, client, known, wants, settings):
            us = mk(location_raw="USA Only")
            ww = mk(location_raw="Worldwide")
            seen["us"], seen["ww"] = wants(us), wants(ww)
            seen["untouched"] = us.remote_scope
            return []

    run(conn, {"r": Rec("r", [])})
    assert seen == {"us": False, "ww": True, "untouched": "unknown"}


def test_settings_mutation_persisted_on_success(conn):
    class Mut(Fixed):
        def fetch(self, client, known, wants, settings):
            settings["hn_last_story"] = "123"
            return []

    run(conn, {"m": Mut("m", [])})
    assert get_setting(conn, "hn_last_story") == "123"


def test_settings_mutation_not_persisted_on_failure(conn):
    class Mut(Fixed):
        def fetch(self, client, known, wants, settings):
            settings["hn_last_story"] = "123"
            raise SourceError("x")

    run(conn, {"m": Mut("m", [])})
    assert get_setting(conn, "hn_last_story") is None


def test_client_closed(conn):
    clients = []

    def factory():
        clients.append(FakeClient())
        return clients[-1]

    collect(conn, sources={"b": Raising("b", SourceError("x"))}, client_factory=factory)
    assert clients[0].closed


def test_concurrent_collect_returns_empty(conn):
    assert collector._lock.acquire(blocking=False)
    try:
        assert run(conn, {"g": Fixed("g", [])}) == []
    finally:
        collector._lock.release()
    assert len(run(conn, {"g": Fixed("g", [])})) == 1


def test_settings_persisted_after_upserts(conn, monkeypatch):
    from jobfinder import db as dbm
    orig = dbm.upsert_job
    seen = []

    def spy(c, job, reason, now):
        seen.append(get_setting(c, "hn_last_story"))
        return orig(c, job, reason, now)

    monkeypatch.setattr(collector.db, "upsert_job", spy)

    class Mut(Fixed):
        def fetch(self, client, known, wants, settings):
            settings["hn_last_story"] = "123"
            return [mk(source="m")]

    run(conn, {"m": Mut("m", [])})
    assert seen == [None]
    assert get_setting(conn, "hn_last_story") == "123"


def test_per_job_failure_isolated(conn, monkeypatch):
    orig = collector.db.upsert_job

    def flaky(c, job, reason, now):
        if job.source_id == "1":
            raise RuntimeError("x")
        return orig(c, job, reason, now)

    monkeypatch.setattr(collector.db, "upsert_job", flaky)
    res = run(conn, {"s1": Fixed("s1", [mk(), mk(source_id="2")])})
    assert res[0].ok and res[0].skipped == 1 and res[0].new == 1
    assert conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0] == 1


def test_close_failure_does_not_break_run(conn):
    class Bad(FakeClient):
        def close(self):
            raise OSError("x")

    res = collect(conn, sources={"g": Fixed("g", [])}, client_factory=Bad)
    assert res[0].ok
    assert last_runs(conn)["g"]["finished_at"]


def _hold_file_lock(db_path):
    """Simulate another process: flock the collect lock through a separate fd."""
    import fcntl
    import os
    fd = os.open(collector.lock_path(db_path), os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def test_file_lock_blocks_collect_across_processes(conn, tmp_path):
    import os
    db_path = tmp_path / "j.db"
    assert collector.db_file(conn) == db_path
    assert not collector.is_running(db_path)
    fd = _hold_file_lock(db_path)
    try:
        assert collector.is_running(db_path)
        assert run(conn, {"good": Fixed("good", [mk(source="good")])}) == []
        assert last_runs(conn) == {}
    finally:
        os.close(fd)
    assert not collector.is_running(db_path)
    assert len(run(conn, {"good": Fixed("good", [])})) == 1  # lock released → runs


def test_file_lock_released_after_collect(conn, tmp_path):
    run(conn, {"good": Fixed("good", [])})
    assert not collector.is_running(tmp_path / "j.db")
    assert not collector._lock.locked()


def test_in_memory_db_skips_file_lock():
    from jobfinder.db import connect
    mem = connect(":memory:")
    assert collector.db_file(mem) is None
    assert len(run(mem, {"good": Fixed("good", [mk(source="good")])})) == 1
