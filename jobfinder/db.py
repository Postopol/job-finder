from __future__ import annotations

import copy
import json
import sqlite3
import zlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import search
from .dedup import dedup_key
from .models import STATUSES, Job

DEFAULT_SETTINGS = {
    "country": "KZ", "interval_hours": 6, "max_pages": 5, "fresh_days": 3,
    "archive_days": 7, "purge_days": 90, "stopwords": [], "hh_token": "",
    "disabled_sources": [],
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
    search.ensure_fts(conn)
    return conn


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


def upsert_job(conn: sqlite3.Connection, job: Job, hidden_reason: str | None,
               now: datetime) -> tuple[int, bool]:
    now_s = _iso(now)
    raw = zlib.compress(json.dumps(job.raw).encode()) if job.raw is not None else None
    published = _iso(job.published_at) if job.published_at else None
    with _tx(conn):
        posting = conn.execute(
            "SELECT id, job_id FROM postings WHERE source=? AND source_id=?",
            (job.source, job.source_id)).fetchone()
        job_id: int | None = posting["job_id"] if posting else None
        key = dedup_key(job.company, job.title)
        if job_id is None and (job.company or "").strip():
            cutoff = _iso(now - timedelta(days=MERGE_WINDOW_DAYS))
            row = conn.execute(
                "SELECT id FROM jobs WHERE dedup_key=? AND last_seen_at>=? ORDER BY id LIMIT 1",
                (key, cutoff)).fetchone()
            job_id = row["id"] if row else None
        is_new = job_id is None
        if is_new:
            usd = _salary_usd_month(conn, job.salary_min, job.salary_max,
                                    job.salary_currency, job.salary_period)
            cols = dict(
                dedup_key=key, source_primary=job.source, title=job.title, company=job.company,
                lang=job.lang, url=job.url, description_html=job.description_html,
                description_text=job.description_text, salary_raw=job.salary_raw,
                salary_min=job.salary_min, salary_max=job.salary_max,
                salary_currency=job.salary_currency, salary_period=job.salary_period,
                salary_usd_month=usd, location_raw=job.location_raw, work_format=job.work_format,
                remote_scope=job.remote_scope, countries=json.dumps(job.countries),
                timezones=json.dumps(job.timezones), seniority=job.seniority,
                stack=json.dumps(job.stack), published_at=published,
                first_seen_at=now_s, last_seen_at=now_s, hidden_reason=hidden_reason)
            cur = conn.execute(
                f"INSERT INTO jobs({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})",
                list(cols.values()))
            job_id = cur.lastrowid
        else:
            old = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

            def keep(name, new):
                return new if new is not None else old[name]

            def keep_list(name, new):
                return json.dumps(new) if new else (old[name] or "[]")

            f = {n: keep(n, getattr(job, n)) for n in (
                "company", "salary_raw", "salary_min", "salary_max", "salary_currency",
                "salary_period", "location_raw", "work_format", "seniority")}
            f["published_at"] = keep("published_at", published)
            f["countries"] = keep_list("countries", job.countries)
            f["timezones"] = keep_list("timezones", job.timezones)
            f["stack"] = keep_list("stack", job.stack)
            f["salary_usd_month"] = _salary_usd_month(
                conn, f["salary_min"], f["salary_max"], f["salary_currency"], f["salary_period"])
            f["dedup_key"] = dedup_key(f["company"], job.title)
            f["title"] = job.title
            f["lang"] = job.lang
            f["remote_scope"] = job.remote_scope
            f["hidden_reason"] = hidden_reason
            if len(job.description_html or "") >= len(old["description_html"] or ""):
                f["description_html"] = job.description_html
                f["description_text"] = job.description_text
            f["last_seen_at"] = now_s
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
               error: str | None, now: datetime, skipped: int = 0) -> None:
    with _tx(conn):
        conn.execute(
            "UPDATE runs SET finished_at=?, ok=?, fetched=?, new=?, error=?, skipped=? WHERE id=?",
            (_iso(now), int(ok), fetched, new, error, skipped, run_id))


def last_runs(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = conn.execute(
        "SELECT * FROM runs WHERE id IN (SELECT MAX(id) FROM runs GROUP BY source)")
    return {r["source"]: r for r in rows}
