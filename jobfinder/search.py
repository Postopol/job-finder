"""Full-text search over jobs: FTS5 on stemmed text, synonyms, section filters."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import Stemmer

log = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[\w+#.]+")
_CYRILLIC_RE = re.compile(r"[а-я]")
_TECH = {"c++": "cplusplus", "c#": "csharp", ".net": "dotnet", "node.js": "nodejs"}
_RU = Stemmer.Stemmer("russian")
_EN = Stemmer.Stemmer("english")

SECTIONS = ("feed", "mine", "archive", "hidden")


def ensure_fts(conn: sqlite3.Connection) -> None:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(jobs_fts)")]
    if cols and "title" not in cols:  # old single-column index: rebuild with a title column
        conn.execute("DROP TABLE jobs_fts")
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5("
                 "title, body, tokenize='unicode61 remove_diacritics 2')")
    # Backfill: FTS table is new/empty but jobs already exist.
    if (conn.execute("SELECT 1 FROM jobs_fts LIMIT 1").fetchone() is None
            and conn.execute("SELECT 1 FROM jobs LIMIT 1").fetchone() is not None):
        for (job_id,) in conn.execute("SELECT id FROM jobs").fetchall():
            index_job(conn, job_id)
        conn.commit()


def _tokens(text: str) -> list[str]:
    out = []
    for tok in _TOKEN_RE.findall((text or "").lower().replace("ё", "е")):
        tok = _TECH.get(tok) or tok.strip(".")
        if not tok or not any(ch.isalnum() for ch in tok):
            continue
        stemmer = _RU if _CYRILLIC_RE.search(tok) else _EN
        out.append(stemmer.stemWord(tok))
    return out


def stem_text(text: str) -> str:
    return " ".join(_tokens(text))


def index_job(conn: sqlite3.Connection, job_id: int) -> None:
    row = conn.execute(
        "SELECT title, company, stack, description_text FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        return
    try:
        stack = " ".join(json.loads(row["stack"] or "[]"))
    except ValueError:
        stack = ""
    body = stem_text(" ".join([row["title"] or "", row["company"] or "", stack,
                               row["description_text"] or ""]))
    conn.execute("DELETE FROM jobs_fts WHERE rowid=?", (job_id,))
    conn.execute("INSERT INTO jobs_fts(rowid, title, body) VALUES(?, ?, ?)",
                 (job_id, stem_text(row["title"] or ""), body))


@lru_cache(maxsize=1)
def _synonym_index() -> dict[str, tuple[str, ...]]:
    data = tomllib.loads(Path(__file__).with_name("synonyms.toml").read_text(encoding="utf-8"))
    index: dict[str, tuple[str, ...]] = {}
    for group in data.get("groups", []):
        stems = tuple(dict.fromkeys(s for t in group for s in _tokens(t)))
        for s in stems:
            index[s] = stems
    return index


def expand_query(q: str) -> str | None:
    """Build a safe FTS5 MATCH expression; never passes user syntax through."""
    index = _synonym_index()
    groups = []
    for tok in _tokens(q):
        terms = index.get(tok, (tok,))
        quoted = [f'"{t.replace(chr(34), "")}"*' for t in terms]
        groups.append(quoted[0] if len(quoted) == 1 else "(" + " OR ".join(quoted) + ")")
    return " AND ".join(groups) if groups else None


@dataclass
class SearchParams:
    text: str = ""
    section: str = "feed"
    sources: list[str] | None = None
    langs: list[str] | None = None
    scopes: list[str] | None = None
    levels: list[str] | None = None  # junior|middle|senior|lead|none
    salary_min_usd: int | None = None
    include_no_salary: bool = True
    fresh_days: int | None = 3
    limit: int = 50
    offset: int = 0


_COLS = ("id, title, company, salary_raw, salary_min, salary_max, salary_currency, "
         "salary_period, remote_scope, location_raw, source_primary, lang, first_seen_at, "
         "COALESCE(s.status, 'new') AS status, hidden_reason")
_FROM = "FROM jobs j LEFT JOIN user_status s ON s.job_id = j.id"
_REJECTED = "COALESCE(s.status, 'new') = 'rejected'"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _section_sql(section: str, p: SearchParams, now: datetime, args: list) -> str:
    if section == "mine":
        return "s.status IN ('interesting', 'applied')"
    if section == "archive":
        return "j.archived_at IS NOT NULL"
    if section == "hidden":
        return f"({_REJECTED} OR j.hidden_reason IS NOT NULL)"
    sql = f"j.archived_at IS NULL AND j.hidden_reason IS NULL AND NOT {_REJECTED}"
    if p.fresh_days is not None:
        sql += " AND j.first_seen_at >= ?"
        args.append(_iso(now - timedelta(days=p.fresh_days)))
    return sql


def _in(column: str, values: list[str], args: list) -> str:
    args.extend(values)
    return f"{column} IN ({', '.join('?' * len(values))})"


def _where(p: SearchParams, section: str, now: datetime) -> tuple[str, list] | None:
    args: list = []
    conds = [_section_sql(section, p, now, args)]
    match = expand_query(p.text)
    if match is not None:
        conds.append("j.id IN (SELECT rowid FROM jobs_fts WHERE jobs_fts MATCH ?)")
        args.append(match)
    for column, values in (("j.source_primary", p.sources), ("j.lang", p.langs),
                           ("j.remote_scope", p.scopes)):
        if values is not None:
            if not values:
                return None  # empty selection matches nothing
            conds.append(_in(column, values, args))
    if p.levels is not None:
        if not p.levels:
            return None
        known = [v for v in p.levels if v != "none"]
        parts = [_in("j.seniority", known, args)] if known else []
        if "none" in p.levels:
            parts.append("j.seniority IS NULL")
        conds.append("(" + " OR ".join(parts) + ")")
    if p.salary_min_usd is not None:
        cond = "j.salary_usd_month >= ?"
        args.append(p.salary_min_usd)
        if p.include_no_salary:
            cond = f"({cond} OR j.salary_usd_month IS NULL)"
        conds.append(cond)
    elif not p.include_no_salary:  # «Показывать без зарплаты» off, no amount entered
        conds.append("j.salary_usd_month IS NOT NULL")
    return " AND ".join(conds), args


def search_jobs(conn: sqlite3.Connection, p: SearchParams, now: datetime) -> list[dict]:
    built = _where(p, p.section, now)
    if built is None:
        return []
    where, args = built
    order, order_args = "j.first_seen_at DESC, j.id DESC", []
    match = expand_query(p.text)
    if match is not None:  # jobs with the query in the title come first
        order = ("j.id IN (SELECT rowid FROM jobs_fts WHERE jobs_fts MATCH ?) DESC, " + order)
        order_args = [f"title : ({match})"]
    try:
        rows = conn.execute(
            f"SELECT {_COLS} {_FROM} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            [*args, *order_args, p.limit, p.offset]).fetchall()
    except sqlite3.OperationalError as e:  # last-resort guard; quoting should prevent this
        log.warning("search failed for %r: %s", p.text, e)
        return []
    return [dict(r) for r in rows]


def count_sections(conn: sqlite3.Connection, p: SearchParams, now: datetime) -> dict[str, int]:
    counts = {}
    for section in SECTIONS:
        built = _where(p, section, now)
        if built is None:
            counts[section] = 0
            continue
        where, args = built
        try:
            counts[section] = conn.execute(
                f"SELECT COUNT(*) {_FROM} WHERE {where}", args).fetchone()[0]
        except sqlite3.OperationalError as e:
            log.warning("count failed for %r: %s", p.text, e)
            counts[section] = 0
    return counts
