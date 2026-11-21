import threading
from datetime import timedelta

from conftest import mk
from jobfinder.db import (all_settings, connect, finish_run, get_job, get_setting,
                          get_status, known_source_ids, last_runs, set_setting,
                          set_status, start_run, upsert_job)


def test_insert_then_update_same_posting(conn, now):
    jid, new = upsert_job(conn, mk(), None, now)
    jid2, new2 = upsert_job(conn, mk(title="Python Developer"), None, now + timedelta(hours=6))
    assert new and not new2 and jid == jid2


def test_cross_source_duplicate_merges_postings(conn, now):
    a, _ = upsert_job(conn, mk(source="hh", source_id="1"), None, now)
    b, new = upsert_job(conn, mk(source="habr", source_id="9", url="https://h/9"), None, now)
    assert a == b and not new
    assert {p["source"] for p in get_job(conn, a)["postings"]} == {"hh", "habr"}


def test_status_survives_recollect(conn, now):
    jid, _ = upsert_job(conn, mk(), None, now)
    set_status(conn, jid, "interesting", now)
    upsert_job(conn, mk(), None, now + timedelta(days=1))
    assert get_status(conn, jid) == "interesting"


def test_reappearing_job_is_unarchived(conn, now):
    jid, _ = upsert_job(conn, mk(), None, now)
    conn.execute("UPDATE jobs SET archived_at=? WHERE id=?", (now.isoformat(), jid))
    upsert_job(conn, mk(), None, now + timedelta(days=10))
    assert get_job(conn, jid)["archived_at"] is None


def test_concurrent_status_write_during_collection(tmp_path, now):  # Review Focus 1
    path = tmp_path / "j.db"
    c1, c2 = connect(path), connect(path)
    jid, _ = upsert_job(c1, mk(), None, now)
    c1.commit()
    c1.execute("BEGIN IMMEDIATE"); upsert_job(c1, mk(source_id="2", url="https://x/2", title="Go Dev"), None, now)
    t = threading.Timer(0.3, c1.commit); t.start()
    set_status(c2, jid, "applied", now)   # waits on busy_timeout, must not raise
    t.join()
    assert get_status(c2, jid) == "applied"


def test_settings_defaults_and_override(conn):
    assert get_setting(conn, "interval_hours") == 6
    set_setting(conn, "stopwords", ["1С"]); assert get_setting(conn, "stopwords") == ["1С"]


def test_settings_unknown_key_and_all(conn):
    assert get_setting(conn, "nope") is None
    set_setting(conn, "max_pages", 9)
    s = all_settings(conn)
    assert s["max_pages"] == 9 and s["country"] == "KZ"


def test_runs_roundtrip(conn, now):
    rid = start_run(conn, "remoteok", now)
    finish_run(conn, rid, False, 0, 0, "HTTP 429", now)
    assert last_runs(conn)["remoteok"]["error"] == "HTTP 429"


def test_finish_run_skipped_and_latest(conn, now):
    r1 = start_run(conn, "hh", now)
    finish_run(conn, r1, True, 5, 2, None, now, skipped=1)
    r2 = start_run(conn, "hh", now + timedelta(hours=6))
    assert last_runs(conn)["hh"]["id"] == r2
    assert conn.execute("SELECT skipped FROM runs WHERE id=?", (r1,)).fetchone()[0] == 1


def test_salary_usd_month(conn, now):
    j = mk(salary_min=1200, salary_max=2400, salary_currency="EUR", salary_period="year")
    jid, _ = upsert_job(conn, j, None, now)
    assert abs(conn.execute("SELECT salary_usd_month FROM jobs WHERE id=?", (jid,)).fetchone()[0]
               - 2400 * 1.08 / 12) < 1e-6
    j2 = mk(source_id="2", title="Other", salary_min=10, salary_currency="USD", salary_period="hour")
    jid2, _ = upsert_job(conn, j2, None, now)
    assert conn.execute("SELECT salary_usd_month FROM jobs WHERE id=?", (jid2,)).fetchone()[0] == 1600
    j3 = mk(source_id="3", title="Third", salary_min=10, salary_currency="XXX")
    jid3, _ = upsert_job(conn, j3, None, now)
    assert conn.execute("SELECT salary_usd_month FROM jobs WHERE id=?", (jid3,)).fetchone()[0] is None


def test_get_job_decoded_and_known_ids(conn, now):
    jid, _ = upsert_job(conn, mk(countries=["KZ"], stack=["python"], raw={"a": 1}), "restricted", now)
    g = get_job(conn, jid)
    assert g["countries"] == ["KZ"] and g["stack"] == ["python"] and g["timezones"] == []
    assert g["status"] == "new" and g["hidden_reason"] == "restricted"
    assert g["postings"][0]["url"] == "https://x/1"
    assert known_source_ids(conn, "s1") == {"1"}
    assert get_job(conn, 999) is None


def test_update_keeps_longer_description_html(conn, now):
    jid, _ = upsert_job(conn, mk(description_html="<p>long long</p>"), None, now)
    upsert_job(conn, mk(description_html="<p>x</p>"), None, now)
    assert get_job(conn, jid)["description_html"] == "<p>long long</p>"


def test_old_duplicate_not_merged(conn, now):
    a, _ = upsert_job(conn, mk(source="hh"), None, now)
    b, new = upsert_job(conn, mk(source="habr", source_id="9"), None, now + timedelta(days=31))
    assert new and a != b
