import json
import threading
from pathlib import Path

import httpx

from jobfinder import collector
from jobfinder.collector import collect
from jobfinder.db import get_setting, last_runs, set_setting
from jobfinder.http import PoliteClient, SourceBlocked, SourceError
from jobfinder.sources import habr
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


class BlockedClient(FakeClient):
    blocked = 429


def test_partly_blocked_source_keeps_jobs_and_notes_block(conn):
    res = collect(conn, sources={"p": Fixed("p", [mk(source="p")])}, client_factory=BlockedClient)
    assert res[0].ok and res[0].new == 1 and "429" in res[0].error
    run_row = last_runs(conn)["p"]
    assert run_row["ok"] == 1 and "без полного описания" in run_row["error"]


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

    def spy(c, job, reason, now, **kw):
        seen.append(get_setting(c, "hn_last_story"))
        return orig(c, job, reason, now, **kw)

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

    def flaky(c, job, reason, now, **kw):
        if job.source_id == "1":
            raise RuntimeError("x")
        return orig(c, job, reason, now, **kw)

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


def test_detail_block_on_two_pages_keeps_all_jobs_and_next_run_stops(conn):
    """habr: 2 list pages, details blocked after the first; every listed job is stored."""
    fix = Path(__file__).parent / "fixtures"
    items = json.loads((fix / "habr.json").read_text(encoding="utf-8"))["list"]
    half = len(items) // 2
    pages = {"1": items[:half], "2": items[half:]}
    detail_html = (fix / "habr_detail.html").read_text(encoding="utf-8")
    details = []

    def handler(req):
        if req.url.path == "/api/frontend/vacancies":
            return httpx.Response(200, json={"list": pages.get(req.url.params["page"], []), "meta": {}})
        details.append(req.url.path)
        if len(details) > 1:
            return httpx.Response(429)
        return httpx.Response(200, text=detail_html, headers={"content-type": "text/html"})

    def factory():
        return PoliteClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)

    listed = [j for j in map(habr.SOURCE.parse_item, items) if j is not None]
    assert {j.source_id for j in listed} & {str(i["id"]) for i in pages["2"]}  # page 2 matters
    res = collect(conn, sources={"habr": habr.SOURCE}, client_factory=factory)
    assert res[0].ok and "429" in res[0].error and len(details) == 2
    stored = {r[0] for r in conn.execute("SELECT source_id FROM postings WHERE source='habr'")}
    assert stored == {j.source_id for j in listed}

    # next run: page 1 is known, paging stops, no lost jobs to come back for
    details.clear()
    res = collect(conn, sources={"habr": habr.SOURCE}, client_factory=factory)
    assert res[0].ok and res[0].new == 0 and details == []


def _habr_twice(conn, detail_text, stopwords=()):
    """Collect one habr item twice: run 1 loads its detail page, run 2 only lists it."""
    fix = Path(__file__).parent / "fixtures"
    items = json.loads((fix / "habr.json").read_text(encoding="utf-8"))["list"]
    item = next(i for i in items if i["title"] == "Middle Golang Разработчик")
    detail = f'<html><div class="vacancy-description__text"><p>{detail_text}</p></div></html>'
    details = []

    def handler(req):
        if req.url.path == "/api/frontend/vacancies":
            page = [item] if req.url.params["page"] == "1" else []
            return httpx.Response(200, json={"list": page, "meta": {}})
        details.append(req.url.path)
        return httpx.Response(200, text=detail, headers={"content-type": "text/html"})

    def factory():
        return PoliteClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)

    set_setting(conn, "stopwords", list(stopwords))
    sid = str(item["id"])
    state = []
    for _ in range(2):
        res = collect(conn, sources={"habr": habr.SOURCE}, client_factory=factory)
        assert res[0].ok
        state.append(dict(conn.execute(
            "SELECT j.hidden_reason, j.remote_scope, j.description_html, j.description_detail "
            "FROM jobs j JOIN postings p ON p.job_id=j.id WHERE p.source='habr' AND p.source_id=?",
            (sid,)).fetchone()))
    assert len(details) == 1  # the second run did not ask for the detail page
    return state


def test_detail_restriction_survives_listing_only_recollect(conn):
    first, second = _habr_twice(conn, "Go backend. Гражданство и локация: только РФ.")
    assert first["hidden_reason"] == "restricted" and first["remote_scope"] == "restricted"
    assert second["hidden_reason"] == "restricted" and second["remote_scope"] == "restricted"
    assert "только РФ" in second["description_html"] and second["description_detail"] == 1


def test_detail_stopword_survives_listing_only_recollect(conn):
    first, second = _habr_twice(conn, "Go backend, немного интеграций с 1С.", stopwords=["1С"])
    assert first["hidden_reason"] == second["hidden_reason"] == "stopword:1с"


def _merged(conn):
    rows = conn.execute("SELECT hidden_reason, remote_scope, countries FROM jobs").fetchall()
    assert len(rows) == 1  # both postings merged into one job
    return rows[0]["hidden_reason"], rows[0]["remote_scope"], json.loads(rows[0]["countries"])


def test_cross_source_merge_hide_reason_independent_of_order(tmp_path):
    from jobfinder.db import connect
    long_ru = mk(source="a", source_id="1",
                 description_html="<p>Python backend. Гражданство: только РФ. " + "x" * 300 + "</p>")
    bare = mk(source="b", source_id="2", url="https://y/2")
    kz = mk(source="c", source_id="3", url="https://z/3", countries=["KZ", "RU"])
    results = []
    for order in ([long_ru, bare], [bare, long_ru]):
        conn = connect(tmp_path / f"{order[0].source}.db")
        for job in order:
            run(conn, {job.source: Fixed(job.source, [job.__class__(**vars(job))])})
        results.append(_merged(conn))
        conn.close()
    assert results[0] == results[1] == ("restricted", "restricted", [])
    # a structured country list kept from another source still decides the scope
    conn = connect(tmp_path / "kz.db")
    for job in (kz, bare):
        run(conn, {job.source: Fixed(job.source, [job.__class__(**vars(job))])})
    assert _merged(conn) == (None, "cis", ["KZ", "RU"])
    conn.close()


def test_is_running_through_symlinked_dir(tmp_path):
    """The CLI/web probe the configured (symlinked) path; collect locks the connection's path."""
    from jobfinder.db import connect
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    conn = connect(link / "j.db")
    try:
        with collector.file_lock(collector.db_file(conn)) as acquired:
            assert acquired
            assert collector.is_running(link / "j.db")
            assert collector.is_running(real / "j.db")
        assert not collector.is_running(link / "j.db")
        assert collector.lock_path(link / "j.db") == collector.lock_path(real / "j.db")
    finally:
        conn.close()


class Recording(Fixed):
    """Records which jobs the collector asked details for and what `known` held."""

    def fetch(self, client, known, wants, settings):
        self.known = set(known)
        self.wanted = [j.source_id for j in self.jobs if wants(j)]
        return list(self.jobs)


def _count(conn, sql="SELECT COUNT(*) FROM jobs"):
    return conn.execute(sql).fetchone()[0]


def test_halal_filter_drops_banned_jobs_without_details(conn):
    jobs = [mk(source="r", source_id="1", url="https://x/1", title="Python Developer"),
            mk(source="r", source_id="2", url="https://x/2", title="Designer (iGaming)"),
            mk(source="r", source_id="3", url="https://x/3", title="Go Developer",
               company="Hidden", description_text="Мы разрабатываем ПО для iGaming.")]
    src = Recording("r", jobs)
    res = run(conn, {"r": src})
    assert src.wanted == ["1"]  # no detail page for a job already seen as banned
    assert _count(conn) == 1 and res[0].new == 1 and res[0].banned == 2
    assert last_runs(conn)["r"]["banned"] == 2
    # next run: banned ids count as known, so the site is not asked about them again
    src2 = Recording("r", jobs)
    run(conn, {"r": src2})
    assert {"2", "3"} <= src2.known and _count(conn) == 1


def test_banned_job_seen_again_without_description_stays_out(conn):
    banned = mk(source="r", source_id="3", url="https://x/3", title="Go Developer",
                company="Hidden", description_text="Мы разрабатываем ПО для iGaming.")
    run(conn, {"r": Fixed("r", [banned])})
    listing_only = mk(source="r", source_id="3", url="https://x/3", title="Go Developer",
                      company="Hidden")
    run(conn, {"r": Fixed("r", [listing_only])})
    assert _count(conn) == 0


def test_halal_filter_off_keeps_everything(conn):
    set_setting(conn, "halal", False)
    src = Recording("r", [mk(source="r", source_id="2", url="https://x/2", title="Designer (iGaming)")])
    res = run(conn, {"r": src})
    assert src.wanted == ["2"] and _count(conn) == 1 and res[0].banned == 0


class Counting(Fixed):
    def fetch(self, client, known, wants, settings):
        self.last_items = 9
        return list(self.jobs)


def test_items_looked_at_are_stored(conn):
    run(conn, {"cnt": Counting("cnt", [mk(source="cnt")]), "plain": Fixed("plain", [])})
    runs = last_runs(conn)
    assert runs["cnt"]["items"] == 9 and runs["cnt"]["fetched"] == 1
    assert runs["plain"]["items"] is None
