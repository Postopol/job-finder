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


def test_no_company_does_not_merge_across_sources(conn, now):
    a, _ = upsert_job(conn, mk(source="hh", company=None), None, now)
    b, new = upsert_job(conn, mk(source="habr", source_id="9", company=None), None, now)
    assert new and a != b


def test_settings_returned_are_copies(conn):
    get_setting(conn, "stopwords").append("x")
    all_settings(conn)["rates"]["USD"] = 99
    assert get_setting(conn, "stopwords") == []
    assert get_setting(conn, "rates")["USD"] == 1


def test_secondary_source_does_not_erase_data(conn, now):
    full = mk(source="hh", salary_min=1000, salary_max=2000, salary_currency="USD",
              salary_period="month", location_raw="Remote", countries=["KZ"], stack=["python"],
              seniority="senior", raw={"a": 1})
    jid, _ = upsert_job(conn, full, None, now)
    bare = mk(source="habr", source_id="9", raw=None)
    upsert_job(conn, bare, None, now)
    g = get_job(conn, jid)
    assert (g["salary_min"], g["salary_max"], g["salary_currency"]) == (1000, 2000, "USD")
    assert g["location_raw"] == "Remote" and g["countries"] == ["KZ"] and g["stack"] == ["python"]
    assert g["seniority"] == "senior"
    assert conn.execute("SELECT salary_usd_month FROM jobs WHERE id=?", (jid,)).fetchone()[0] == 2000


def test_update_without_reason_fn_stores_given_scope_and_reason(conn, now):
    jid, _ = upsert_job(conn, mk(remote_scope="worldwide"), "x", now)
    upsert_job(conn, mk(remote_scope="cis"), None, now)
    g = get_job(conn, jid)
    assert g["remote_scope"] == "cis" and g["hidden_reason"] is None


def test_raw_roundtrip_and_kept_on_none(conn, now):
    import json, zlib
    jid, _ = upsert_job(conn, mk(raw={"k": "значение"}), None, now)
    upsert_job(conn, mk(raw=None), None, now)
    blob = conn.execute("SELECT raw FROM postings WHERE job_id=?", (jid,)).fetchone()[0]
    assert json.loads(zlib.decompress(blob)) == {"k": "значение"}


def test_set_status_rejects_unknown(conn, now):
    import pytest
    jid, _ = upsert_job(conn, mk(), None, now)
    with pytest.raises(ValueError):
        set_status(conn, jid, "bogus", now)


def test_salary_merged_as_one_group(conn, now):
    jid, _ = upsert_job(conn, mk(source="a", salary_raw="до $5000", salary_max=5000,
                                 salary_currency="USD", salary_period="month"), None, now)
    upsert_job(conn, mk(source="b", source_id="2", salary_raw="от €3000", salary_min=3000,
                        salary_currency="EUR", salary_period="year"), None, now)
    g = get_job(conn, jid)
    assert (g["salary_raw"], g["salary_min"], g["salary_max"], g["salary_currency"],
            g["salary_period"]) == ("от €3000", 3000, None, "EUR", "year")
    upsert_job(conn, mk(source="c", source_id="3", salary_raw="competitive",
                        salary_currency="GBP", salary_period="hour"), None, now)
    g = get_job(conn, jid)  # no amount: the whole stored group stays
    assert (g["salary_raw"], g["salary_min"], g["salary_max"], g["salary_currency"],
            g["salary_period"]) == ("от €3000", 3000, None, "EUR", "year")


def test_reason_fn_sees_merged_record(conn, now):
    jid, _ = upsert_job(conn, mk(description_html="<p>long detail text</p>",
                                 description_text="long detail text", location_raw="Berlin"),
                        None, now)
    seen = []

    def reason_fn(job):
        seen.append((job.description_text, job.location_raw))
        return "x"

    upsert_job(conn, mk(), None, now, reason_fn=reason_fn)
    assert seen == [("long detail text", "Berlin")]
    assert get_job(conn, jid)["hidden_reason"] == "x"


def test_old_db_gets_description_detail_column(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, dedup_key TEXT NOT NULL, "
                "source_primary TEXT NOT NULL, title TEXT NOT NULL, company TEXT, lang TEXT, "
                "url TEXT, description_html TEXT, description_text TEXT, salary_raw TEXT, "
                "salary_min INTEGER, salary_max INTEGER, salary_currency TEXT, salary_period TEXT, "
                "salary_usd_month REAL, location_raw TEXT, work_format TEXT, remote_scope TEXT, "
                "countries TEXT, timezones TEXT, seniority TEXT, stack TEXT, published_at TEXT, "
                "first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, archived_at TEXT, "
                "hidden_reason TEXT)")
    old.execute("INSERT INTO jobs(dedup_key, source_primary, title, first_seen_at, last_seen_at) "
                "VALUES('k', 's', 'T', 'a', 'a')")
    old.commit()
    old.close()
    c = connect(path)
    row = c.execute("SELECT description_detail FROM jobs").fetchone()
    assert row["description_detail"] is None  # unknown for rows stored before the flag
    c.close()


def test_same_key_different_level_not_merged(conn, now):
    a, _ = upsert_job(conn, mk(source="hh", source_id="1", title="Middle Python Developer"), None, now)
    b, new = upsert_job(conn, mk(source="habr", source_id="2", title="Senior Python Developer"),
                        None, now)
    assert new and a != b


def test_compatible_row_found_among_same_key(conn, now):
    a, _ = upsert_job(conn, mk(source="hh", source_id="1", title="Middle Python Developer"), None, now)
    b, _ = upsert_job(conn, mk(source="hh", source_id="2", title="Senior Python Developer"), None, now)
    c, new = upsert_job(conn, mk(source="habr", source_id="3", title="Python Developer (Senior)"),
                        None, now)
    assert not new and c == b
