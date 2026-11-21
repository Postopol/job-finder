import json
import zlib
from datetime import timedelta

from jobfinder import archive, db, search
from jobfinder.models import Job
from jobfinder.sources.base import Source
from tests.conftest import mk


class FakeSource(Source):
    lang = "en"
    method = "test"

    def __init__(self, name, full_listing=True, title="Reparsed Title"):
        self.name = name
        self.full_listing = full_listing
        self.title = title

    def parse_item(self, item):
        if item.get("skip"):
            return None
        return Job(source=self.name, source_id=str(item["id"]), url="https://x/" + str(item["id"]),
                   title=self.title, company="Acme", salary_min=item.get("sal"),
                   salary_max=item.get("sal"), salary_currency="USD" if item.get("sal") else None,
                   salary_period="month" if item.get("sal") else None)

    def fetch(self, client, known, wants, settings):
        return []


def run(conn, source, when, ok):
    rid = db.start_run(conn, source, when)
    db.finish_run(conn, rid, ok, 0, 0, None if ok else "boom", when)


def archived(conn, job_id):
    return db.get_job(conn, job_id)["archived_at"]


def test_full_listing_job_archived_after_7_days_when_source_healthy(conn, now):
    jid, _ = db.upsert_job(conn, mk(), None, now - timedelta(days=8))
    run(conn, "s1", now - timedelta(hours=6), True)
    assert archive.archive_stale(conn, now, {"s1": FakeSource("s1")}) == 1
    assert archived(conn, jid) is not None
    assert archive.archive_stale(conn, now, {"s1": FakeSource("s1")}) == 0


def test_recent_job_not_archived(conn, now):
    jid, _ = db.upsert_job(conn, mk(), None, now - timedelta(days=3))
    run(conn, "s1", now - timedelta(hours=1), True)
    assert archive.archive_stale(conn, now, {"s1": FakeSource("s1")}) == 0
    assert archived(conn, jid) is None


def test_not_archived_when_source_failing(conn, now):
    jid, _ = db.upsert_job(conn, mk(), None, now - timedelta(days=8))
    for d in range(7):
        run(conn, "s1", now - timedelta(days=d, hours=1), False)
    assert archive.archive_stale(conn, now, {"s1": FakeSource("s1")}) == 0
    assert archived(conn, jid) is None


def test_incremental_source_archived_after_30_days(conn, now):
    old, _ = db.upsert_job(conn, mk(source_id="1"), None, now - timedelta(days=31))
    young, _ = db.upsert_job(conn, mk(source_id="2", title="Other", company="Beta"), None,
                             now - timedelta(days=20))
    srcs = {"s1": FakeSource("s1", full_listing=False)}
    assert archive.archive_stale(conn, now, srcs) == 1
    assert archived(conn, old) is not None
    assert archived(conn, young) is None


def test_job_with_two_postings_needs_both_stale(conn, now):
    jid, _ = db.upsert_job(conn, mk(source="s1", source_id="1"), None, now - timedelta(days=10))
    db.upsert_job(conn, mk(source="s2", source_id="9"), None, now - timedelta(days=1))
    run(conn, "s1", now - timedelta(hours=1), True)
    run(conn, "s2", now - timedelta(hours=1), True)
    srcs = {"s1": FakeSource("s1"), "s2": FakeSource("s2")}
    assert archive.archive_stale(conn, now, srcs) == 0
    assert archived(conn, jid) is None
    assert archive.archive_stale(conn, now + timedelta(days=8), srcs) == 0  # runs too old
    run(conn, "s1", now + timedelta(days=8), True)
    run(conn, "s2", now + timedelta(days=8), True)
    assert archive.archive_stale(conn, now + timedelta(days=8), srcs) == 1


def test_unknown_source_treated_as_full_listing(conn, now):
    jid, _ = db.upsert_job(conn, mk(source="gone"), None, now - timedelta(days=8))
    assert archive.archive_stale(conn, now, {}) == 0
    run(conn, "gone", now - timedelta(hours=1), True)
    assert archive.archive_stale(conn, now, {}) == 1
    assert archived(conn, jid) is not None


def test_purge_keeps_marked_jobs(conn, now):
    long_ago = now - timedelta(days=100)
    a, _ = db.upsert_job(conn, mk(source_id="1", raw={"id": 1}), None, long_ago)
    b, _ = db.upsert_job(conn, mk(source_id="2", title="T2", company="B", raw={"id": 2}), None, long_ago)
    c, _ = db.upsert_job(conn, mk(source_id="3", title="T3", company="C", raw={"id": 3}), None, long_ago)
    d, _ = db.upsert_job(conn, mk(source_id="4", title="T4", company="D", raw={"id": 4}), None, now)
    db.set_status(conn, a, "interesting", now)
    db.set_status(conn, b, "seen", now)
    conn.execute("UPDATE jobs SET archived_at=? WHERE id IN (?,?,?)",
                 (db._iso(long_ago), a, b, c))
    conn.commit()
    assert archive.purge_raw(conn, now) == 2

    def raw(j):
        return conn.execute("SELECT raw FROM postings WHERE job_id=?", (j,)).fetchone()[0]
    assert raw(a) is not None
    assert raw(b) is None
    assert raw(c) is None
    assert raw(d) is not None


def test_reparse_updates_fields_keeps_status(conn, now):
    seen = now - timedelta(days=2)
    jid, _ = db.upsert_job(conn, mk(raw={"id": 1}), None, seen)
    db.set_status(conn, jid, "applied", now)
    before = db.get_job(conn, jid)
    n = archive.reparse(conn, None, {"s1": FakeSource("s1")})
    assert n == 1
    after = db.get_job(conn, jid)
    assert after["title"] == "Reparsed Title"
    assert after["status"] == "applied"
    assert after["first_seen_at"] == before["first_seen_at"]
    assert after["last_seen_at"] == before["last_seen_at"]
    q = search.stem_text("reparsed").split()[0]
    assert conn.execute("SELECT 1 FROM jobs_fts WHERE jobs_fts MATCH ?", (q,)).fetchone()


def test_reparse_skips_none_and_missing_raw(conn, now):
    a, _ = db.upsert_job(conn, mk(source_id="1", raw={"id": 1, "skip": True}), None, now)
    b, _ = db.upsert_job(conn, mk(source_id="2", title="Keep", company="B"), None, now)
    assert archive.reparse(conn, None, {"s1": FakeSource("s1")}) == 0
    assert db.get_job(conn, a)["title"] == "Python Developer"
    assert db.get_job(conn, b)["title"] == "Keep"


def test_reparse_merges_postings_keeps_salary(conn, now):
    jid, _ = db.upsert_job(conn, mk(source="s1", source_id="1", raw={"id": 1}), None, now)
    db.upsert_job(conn, mk(source="s2", source_id="2", raw={"id": 2, "sal": 5000}), None, now)
    srcs = {"s1": FakeSource("s1"), "s2": FakeSource("s2")}
    assert archive.reparse(conn, None, srcs) == 1
    j = db.get_job(conn, jid)
    assert j["salary_max"] == 5000
    assert j["salary_usd_month"] == 5000


def test_reparse_updates_dedup_key_and_salary_usd(conn, now):
    jid, _ = db.upsert_job(conn, mk(raw={"id": 1, "sal": 1000}), None, now)
    before = db.get_job(conn, jid)
    conn.execute("UPDATE postings SET raw=? WHERE job_id=?",
                 (zlib.compress(json.dumps({"id": 1, "sal": 2000}).encode()), jid))
    assert archive.reparse(conn, None, {"s1": FakeSource("s1", title="Rust Engineer")}) == 1
    after = db.get_job(conn, jid)
    assert after["dedup_key"] != before["dedup_key"]
    assert after["salary_usd_month"] == 2000


def test_reparse_keeps_values_when_a_posting_lost_raw(conn, now):
    jid, _ = db.upsert_job(conn, mk(source="s1", source_id="1", raw={"id": 1}), None, now)
    db.upsert_job(conn, mk(source="s2", source_id="2", salary_min=5000, salary_max=5000,
                                    salary_currency="USD", salary_period="month",
                                    raw={"id": 2, "sal": 5000}), None, now)
    conn.execute("UPDATE postings SET raw=NULL WHERE source='s2'")
    srcs = {"s1": FakeSource("s1", title="New Title"), "s2": FakeSource("s2")}
    assert archive.reparse(conn, None, srcs) == 1
    j = db.get_job(conn, jid)
    assert j["title"] == "New Title"
    assert j["salary_max"] == 5000


def test_reparse_all_raw_allows_field_to_become_none(conn, now):
    jid, _ = db.upsert_job(conn, mk(salary_min=1, salary_max=1, salary_currency="USD",
                                    salary_period="month", raw={"id": 1}), None, now)
    assert archive.reparse(conn, None, {"s1": FakeSource("s1")}) == 1
    assert db.get_job(conn, jid)["salary_max"] is None


def test_reparse_isolates_corrupt_raw(conn, now):
    a, _ = db.upsert_job(conn, mk(source_id="1", raw={"id": 1}), None, now)
    b, _ = db.upsert_job(conn, mk(source_id="2", title="T2", company="B", raw={"id": 2}), None, now)
    conn.execute("UPDATE postings SET raw=? WHERE job_id=?", (b"garbage", a))
    assert archive.reparse(conn, None, {"s1": FakeSource("s1")}) == 1
    assert db.get_job(conn, b)["title"] == "Reparsed Title"
    assert db.get_job(conn, a)["title"] == "Python Developer"


def test_reparse_keeps_detail_description_and_filters_on_it(conn, now):
    # list raw has no description; the stored one came from a detail page
    detail = "<p>Python backend. Гражданство/локация: только РФ</p>"
    jid, _ = db.upsert_job(conn, mk(raw={"id": 1}, description_html=detail,
                                    description_text="Python backend. Гражданство/локация: только РФ"),
                           "restricted", now)
    assert archive.reparse(conn, None, {"s1": FakeSource("s1")}) == 1
    j = db.get_job(conn, jid)
    assert j["title"] == "Reparsed Title"
    assert j["description_html"] == detail
    assert j["hidden_reason"] == "restricted"
