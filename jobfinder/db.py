from __future__ import annotations

import copy
import json
import sqlite3
import zlib
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import search
from .dedup import compatible, dedup_key
from .models import STATUSES, Job

DEFAULT_SETTINGS = {
    "country": "KZ", "interval_hours": 6, "max_pages": 5, "fresh_days": 3,
    "archive_days": 7, "purge_days": 90, "stopwords": [], "hh_token": "",
    "disabled_sources": [], "halal": True,
    # public channels read via t.me/s/ (checked 2026-11-22: alive, mostly vacancies)
    "tg_channels": ["opento_dev", "opento_data", "pythonrabota", "devops_jobs_feed", "jobforqa",
                    "datasciencejobs", "analytics_jobs", "product_jobs"],
    "rates": {"USD": 1, "EUR": 1.08, "GBP": 1.27, "RUB": 0.011, "KZT": 0.002},
}

MERGE_WINDOW_DAYS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    dedup_key TEXT NOT NULL,
    source_primary TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT,
    lang TEXT,
    url TEXT,
    description_html TEXT,
    description_text TEXT,
    description_detail INTEGER,
    salary_raw TEXT,
    salary_min INTEGER,
    salary_max INTEGER,
    salary_currency TEXT,
    salary_period TEXT,
    salary_usd_month REAL,
    location_raw TEXT,
    work_format TEXT,
    remote_scope TEXT,
    countries TEXT,
    timezones TEXT,
    seniority TEXT,
    stack TEXT,
    published_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    archived_at TEXT,
    hidden_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_dedup ON jobs(dedup_key, last_seen_at);
CREATE TABLE IF NOT EXISTS postings (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    url TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    raw BLOB,
    UNIQUE(source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_postings_job ON postings(job_id);
CREATE TABLE IF NOT EXISTS user_status (
    job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    ok INTEGER,
    fetched INTEGER,
    new INTEGER,
    error TEXT,
    skipped INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS banned (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    seen_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def connect(path: Path | str) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    search.ensure_fts(conn)
    return conn


# Columns added after the first release: (table, column, declaration).
_ADDED_COLUMNS = [
    ("runs", "skipped", "INTEGER NOT NULL DEFAULT 0"),
    ("runs", "banned", "INTEGER NOT NULL DEFAULT 0"),
    # 1 = description from a detail page, 0 = from the listing, NULL = stored before tracking
    ("jobs", "description_detail", "INTEGER"),
    # items the source looked at (Telegram: text posts); NULL when the source does not count
    ("runs", "items", "INTEGER"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, decl in _ADDED_COLUMNS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


@contextmanager
def _tx(conn: sqlite3.Connection):
    """Own the transaction unless the caller already opened one."""
    if conn.in_transaction:
        yield
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


# --- settings -------------------------------------------------------------

def get_setting(conn: sqlite3.Connection, key: str):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if row is not None:
        return json.loads(row["value"])
    return copy.deepcopy(DEFAULT_SETTINGS.get(key))


def all_settings(conn: sqlite3.Connection) -> dict:
    stored = {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT key, value FROM settings")}
    return {**copy.deepcopy(DEFAULT_SETTINGS), **stored}


def set_setting(conn: sqlite3.Connection, key: str, value) -> None:
    with _tx(conn):
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )


# --- jobs -----------------------------------------------------------------

def _salary_usd_month(conn: sqlite3.Connection, smin, smax, currency, period) -> float | None:
    amount = smax if smax is not None else smin
    if amount is None:
        return None
    rate = (get_setting(conn, "rates") or {}).get(currency)
    if rate is None:
        return None
    value = amount * rate
    if period == "year":
        value /= 12
    elif period == "hour":
        value *= 160
    return value


SALARY_FIELDS = ("salary_raw", "salary_min", "salary_max", "salary_currency", "salary_period")


def merge_salary(job: Job, old) -> None:
    """Salary is one group: amounts, currency and period always come from the same posting.

    The incoming job wins when it has an amount; otherwise the stored group is kept.
    `old` is anything indexable by field name (a row or a dict)."""
    if job.salary_min is not None or job.salary_max is not None:
        return
    if old["salary_min"] is not None or old["salary_max"] is not None:
        for n in SALARY_FIELDS:
            setattr(job, n, old[n])
    elif job.salary_raw is None:
        job.salary_raw = old["salary_raw"]


def _merge_stored(job: Job, old: sqlite3.Row) -> None:
    """Fill the incoming (normalized, not yet classified) job with what the stored record
    keeps, so that scope and hide reason are computed on the merged record."""
    for n in ("company", "location_raw", "work_format", "seniority"):
        if getattr(job, n) is None:
            setattr(job, n, old[n])
    if job.published_at is None and old["published_at"]:
        job.published_at = datetime.fromisoformat(old["published_at"])
    for n in ("countries", "timezones", "stack"):
        if not getattr(job, n):
            setattr(job, n, json.loads(old[n] or "[]"))
    merge_salary(job, old)
    if len(job.description_html or "") < len(old["description_html"] or ""):
        job.description_html = old["description_html"]
        job.description_text = old["description_text"]
        detail = old["description_detail"]
        job.description_detail = None if detail is None else bool(detail)


def upsert_job(conn: sqlite3.Connection, job: Job, hidden_reason: str | None,
               now: datetime, *,
               reason_fn: Callable[[Job], str | None] | None = None) -> tuple[int, bool]:
    """Insert a job or merge it into the stored one.

    With `reason_fn`, `job` must be normalized but not yet classified: it is merged with
    the stored record in place (longer description, kept fields), then `reason_fn(job)`
    sets its scope and returns the hide reason. Without it, `hidden_reason` is stored as is.
    """
    now_s = _iso(now)
    raw = zlib.compress(json.dumps(job.raw).encode()) if job.raw is not None else None
    with _tx(conn):
        posting = conn.execute(
            "SELECT id, job_id FROM postings WHERE source=? AND source_id=?",
            (job.source, job.source_id)).fetchone()
        job_id: int | None = posting["job_id"] if posting else None
        key = dedup_key(job.company, job.title)
        if job_id is None and (job.company or "").strip():
            cutoff = _iso(now - timedelta(days=MERGE_WINDOW_DAYS))
            rows = conn.execute(
                "SELECT id, title FROM jobs WHERE dedup_key=? AND last_seen_at>=? ORDER BY id",
                (key, cutoff)).fetchall()
            job_id = next((r["id"] for r in rows if compatible(r["title"], job.title)), None)
        is_new = job_id is None
        if not is_new:
            _merge_stored(job, conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
        if reason_fn is not None:
            hidden_reason = reason_fn(job)
        f = dict(
            dedup_key=dedup_key(job.company, job.title), title=job.title, company=job.company,
            lang=job.lang, description_html=job.description_html,
            description_text=job.description_text,
            description_detail=None if job.description_detail is None else int(job.description_detail),
            salary_raw=job.salary_raw, salary_min=job.salary_min, salary_max=job.salary_max,
            salary_currency=job.salary_currency, salary_period=job.salary_period,
            salary_usd_month=_salary_usd_month(conn, job.salary_min, job.salary_max,
                                               job.salary_currency, job.salary_period),
            location_raw=job.location_raw, work_format=job.work_format,
            remote_scope=job.remote_scope, countries=json.dumps(job.countries),
            timezones=json.dumps(job.timezones), seniority=job.seniority,
            stack=json.dumps(job.stack),
            published_at=_iso(job.published_at) if job.published_at else None,
            last_seen_at=now_s, hidden_reason=hidden_reason)
        if is_new:
            f.update(source_primary=job.source, url=job.url, first_seen_at=now_s)
            cur = conn.execute(
                f"INSERT INTO jobs({', '.join(f)}) VALUES({', '.join('?' * len(f))})",
                list(f.values()))
            job_id = cur.lastrowid
        else:
            f["archived_at"] = None
            sets = ", ".join(f"{k}=?" for k in f)
            conn.execute(f"UPDATE jobs SET {sets} WHERE id=?", [*f.values(), job_id])
        if posting:
            conn.execute("UPDATE postings SET url=?, last_seen_at=?, raw=COALESCE(?, raw) WHERE id=?",
                         (job.url, now_s, raw, posting["id"]))
        else:
            conn.execute(
                "INSERT INTO postings(job_id, source, source_id, url, first_seen_at, last_seen_at, raw) "
                "VALUES(?,?,?,?,?,?,?)",
                (job_id, job.source, job.source_id, job.url, now_s, now_s, raw))
        search.index_job(conn, job_id)
    return job_id, is_new


def update_job_fields(conn: sqlite3.Connection, job_id: int, job: Job,
                      hidden_reason: str | None) -> None:
    """Overwrite a job's parsed fields (reparse); timestamps and status untouched."""
    f = dict(
        dedup_key=dedup_key(job.company, job.title), title=job.title, company=job.company,
        lang=job.lang, description_html=job.description_html,
        description_text=job.description_text,
        description_detail=None if job.description_detail is None else int(job.description_detail),
        salary_raw=job.salary_raw,
        salary_min=job.salary_min, salary_max=job.salary_max,
        salary_currency=job.salary_currency, salary_period=job.salary_period,
        salary_usd_month=_salary_usd_month(conn, job.salary_min, job.salary_max,
                                           job.salary_currency, job.salary_period),
        location_raw=job.location_raw, work_format=job.work_format,
        remote_scope=job.remote_scope, countries=json.dumps(job.countries),
        timezones=json.dumps(job.timezones), seniority=job.seniority,
        stack=json.dumps(job.stack),
        published_at=_iso(job.published_at) if job.published_at else None,
        hidden_reason=hidden_reason)
    with _tx(conn):
        conn.execute(f"UPDATE jobs SET {', '.join(f'{k}=?' for k in f)} WHERE id=?",
                     [*f.values(), job_id])
        search.index_job(conn, job_id)


def split_off(conn: sqlite3.Connection, job_id: int, posting_ids: list[int], job: Job,
              hidden_reason: str | None) -> int:
    """Move postings that were merged into `job_id` by mistake to a new job built from
    `job` (their merged parse). Status stays with the old job; dates come from the postings."""
    marks = ",".join("?" * len(posting_ids))
    with _tx(conn):
        first = conn.execute(f"SELECT MIN(first_seen_at) AS fs, MAX(last_seen_at) AS ls "
                             f"FROM postings WHERE id IN ({marks})", posting_ids).fetchone()
        primary = conn.execute(f"SELECT source, url FROM postings WHERE id IN ({marks}) "
                               f"ORDER BY id LIMIT 1", posting_ids).fetchone()
        archived = conn.execute("SELECT archived_at FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO jobs(dedup_key, source_primary, title, url, first_seen_at, last_seen_at, "
            "archived_at) VALUES(?,?,?,?,?,?,?)",
            (dedup_key(job.company, job.title), primary["source"], job.title, primary["url"],
             first["fs"], first["ls"], archived))
        new_id = cur.lastrowid
        conn.execute(f"UPDATE postings SET job_id=? WHERE id IN ({marks})", [new_id, *posting_ids])
        update_job_fields(conn, new_id, job, hidden_reason)
    return new_id


def banned_ids(conn: sqlite3.Connection, source: str) -> set[str]:
    """Ids the halal filter dropped: not stored as jobs, not asked about again."""
    return {r[0] for r in conn.execute("SELECT source_id FROM banned WHERE source=?", (source,))}


def add_banned(conn: sqlite3.Connection, source: str, source_id: str, reason: str,
               now: datetime) -> None:
    with _tx(conn):
        conn.execute("INSERT OR REPLACE INTO banned(source, source_id, reason, seen_at) "
                     "VALUES(?,?,?,?)", (source, source_id, reason, _iso(now)))


def known_source_ids(conn: sqlite3.Connection, source: str) -> set[str]:
    return {r[0] for r in conn.execute("SELECT source_id FROM postings WHERE source=?", (source,))}


def get_job(conn: sqlite3.Connection, job_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    for k in ("countries", "timezones", "stack"):
        d[k] = json.loads(d[k]) if d[k] else []
    d["status"] = get_status(conn, job_id)
    d["postings"] = [dict(p) for p in conn.execute(
        "SELECT source, url FROM postings WHERE job_id=? ORDER BY id", (job_id,))]
    return d


# --- statuses -------------------------------------------------------------

def set_status(conn: sqlite3.Connection, job_id: int, status: str, now: datetime) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status!r}")
    with _tx(conn):
        conn.execute(
            "INSERT INTO user_status(job_id, status, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(job_id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at",
            (job_id, status, _iso(now)))


def get_status(conn: sqlite3.Connection, job_id: int) -> str:
    row = conn.execute("SELECT status FROM user_status WHERE job_id=?", (job_id,)).fetchone()
    return row["status"] if row else "new"


# --- runs -----------------------------------------------------------------

def start_run(conn: sqlite3.Connection, source: str, now: datetime) -> int:
    with _tx(conn):
        cur = conn.execute("INSERT INTO runs(source, started_at) VALUES(?,?)", (source, _iso(now)))
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, ok: bool, fetched: int, new: int,
               error: str | None, now: datetime, skipped: int = 0, banned: int = 0,
               items: int | None = None) -> None:
    with _tx(conn):
        conn.execute(
            "UPDATE runs SET finished_at=?, ok=?, fetched=?, new=?, error=?, skipped=?, banned=?, "
            "items=? WHERE id=?",
            (_iso(now), int(ok), fetched, new, error, skipped, banned, items, run_id))


def recent_max_fetched(conn: sqlite3.Connection, source: str, runs: int = 5) -> int:
    """Most jobs a source returned in its last `runs` successful runs before the latest one."""
    row = conn.execute(
        "SELECT MAX(fetched) FROM (SELECT fetched FROM runs WHERE source=? AND ok=1 "
        "AND id < (SELECT MAX(id) FROM runs WHERE source=?) ORDER BY id DESC LIMIT ?)",
        (source, source, runs)).fetchone()
    return row[0] or 0


def source_quality(conn: sqlite3.Connection) -> dict[str, dict]:
    """Per source (primary) over active jobs: total and % without salary, stack, level."""
    rows = conn.execute(
        "SELECT source_primary, COUNT(*), "
        "SUM(salary_min IS NULL AND salary_max IS NULL), "
        "SUM(stack IS NULL OR stack = '[]'), SUM(seniority IS NULL) "
        "FROM jobs WHERE archived_at IS NULL GROUP BY source_primary").fetchall()
    return {r[0]: {"total": r[1], "no_salary": round(100 * r[2] / r[1]),
                   "no_stack": round(100 * r[3] / r[1]), "no_level": round(100 * r[4] / r[1])}
            for r in rows}


def last_runs(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = conn.execute(
        "SELECT * FROM runs WHERE id IN (SELECT MAX(id) FROM runs GROUP BY source)")
    return {r["source"]: r for r in rows}
