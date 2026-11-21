from __future__ import annotations

import copy
import json
import logging
import zlib
from datetime import datetime, timedelta

from . import db
from .collector import _prepare
from .filters import FilterConfig
from .models import Job
from .sources import REGISTRY
from .sources.base import Source

log = logging.getLogger(__name__)
INCREMENTAL_ARCHIVE_DAYS = 30
OK_RUN_WINDOW_DAYS = 2


def archive_stale(conn, now: datetime, sources: dict[str, Source] | None = None) -> int:
    """Archive jobs whose every posting is stale (see Global Constraints archive rule)."""
    sources = REGISTRY if sources is None else sources
    seen_cutoff = db._iso(now - timedelta(days=db.get_setting(conn, "archive_days")))
    first_cutoff = db._iso(now - timedelta(days=INCREMENTAL_ARCHIVE_DAYS))
    run_cutoff = db._iso(now - timedelta(days=OK_RUN_WINDOW_DAYS))
    healthy = {r[0] for r in conn.execute(
        "SELECT DISTINCT source FROM runs WHERE ok=1 AND started_at>=?", (run_cutoff,))}

    def qualifies(source: str, first_seen: str, last_seen: str) -> bool:
        src = sources.get(source)
        if src is not None and not src.full_listing:
            return first_seen < first_cutoff
        return last_seen < seen_cutoff and source in healthy

    rows = conn.execute(
        "SELECT p.job_id, p.source, p.first_seen_at, p.last_seen_at FROM postings p "
        "JOIN jobs j ON j.id=p.job_id WHERE j.archived_at IS NULL").fetchall()
    verdict: dict[int, bool] = {}
    for r in rows:
        ok = qualifies(r["source"], r["first_seen_at"], r["last_seen_at"])
        verdict[r["job_id"]] = verdict.get(r["job_id"], True) and ok
    ids = [j for j, ok in verdict.items() if ok]
    if not ids:
        return 0
    now_s = db._iso(now)
    with db._tx(conn):
        conn.executemany("UPDATE jobs SET archived_at=? WHERE id=?", [(now_s, j) for j in ids])
    return len(ids)


def purge_raw(conn, now: datetime) -> int:
    """Drop raw of postings of jobs archived longer than purge_days ago, status new/seen."""
    cutoff = db._iso(now - timedelta(days=db.get_setting(conn, "purge_days")))
    with db._tx(conn):
        cur = conn.execute(
            "UPDATE postings SET raw=NULL WHERE raw IS NOT NULL AND job_id IN ("
            "SELECT j.id FROM jobs j LEFT JOIN user_status s ON s.job_id=j.id "
            "WHERE j.archived_at IS NOT NULL AND j.archived_at<? "
            "AND COALESCE(s.status, 'new') IN ('new', 'seen'))", (cutoff,))
    return cur.rowcount


_SCALARS = ("company", "salary_raw", "salary_min", "salary_max", "salary_currency",
            "salary_period", "location_raw", "work_format", "seniority", "published_at")
_LISTS = ("countries", "timezones", "stack")


def _merge(jobs: list[Job]) -> Job:
    """Merge parsed postings of one job like upsert does; the first one is primary."""
    merged = copy.deepcopy(jobs[0])
    for other in jobs[1:]:
        for n in _SCALARS:
            if getattr(merged, n) is None:
                setattr(merged, n, getattr(other, n))
        for n in _LISTS:
            if not getattr(merged, n):
                setattr(merged, n, getattr(other, n))
        if len(other.description_html or "") > len(merged.description_html or ""):
            merged.description_html = other.description_html
            merged.description_text = other.description_text
    return merged


def _keep_existing(conn, job_id: int, merged: Job) -> None:
    """Some postings were not re-parsed: do not erase what they contributed."""
    old = db.get_job(conn, job_id)
    for n in _SCALARS:
        if getattr(merged, n) is None and old[n] is not None:
            val = old[n]
            setattr(merged, n, datetime.fromisoformat(val) if n == "published_at" else val)
    for n in _LISTS:
        if not getattr(merged, n):
            setattr(merged, n, old[n])
    if len(old["description_html"] or "") > len(merged.description_html or ""):
        merged.description_html = old["description_html"]
        merged.description_text = old["description_text"]


def reparse(conn, source: str | None = None, sources: dict[str, Source] | None = None) -> int:
    """Re-parse saved raw with current parsers, no network. Returns updated jobs count."""
    sources = REGISTRY if sources is None else sources
    settings = db.all_settings(conn)
    cfg = FilterConfig(country=settings["country"], stopwords=settings["stopwords"])
    query = ("SELECT p.job_id, p.source, p.raw FROM postings p JOIN jobs j ON j.id=p.job_id "
             "WHERE p.raw IS NOT NULL")
    args: tuple = ()
    if source is not None:
        query += " AND p.job_id IN (SELECT job_id FROM postings WHERE source=?)"
        args = (source,)
    by_job: dict[int, list] = {}
    for r in conn.execute(query + " ORDER BY (p.source=j.source_primary) DESC, p.id",
                          args).fetchall():
        by_job.setdefault(r["job_id"], []).append(r)
    count = 0
    for job_id, posts in by_job.items():
        try:
            parsed = []
            for r in posts:
                src = sources.get(r["source"])
                if src is None:
                    continue
                job = src.parse_item(json.loads(zlib.decompress(r["raw"])))
                if job is None:
                    continue
                parsed.append((job, _prepare(job, cfg)))
            if not parsed:
                continue
            merged = _merge([j for j, _ in parsed])
            total = conn.execute("SELECT COUNT(*) FROM postings WHERE job_id=?",
                                 (job_id,)).fetchone()[0]
            if len(parsed) < total:
                _keep_existing(conn, job_id, merged)
            db.update_job_fields(conn, job_id, merged, parsed[0][1])
            count += 1
        except Exception:
            log.warning("reparse: не удалось обработать вакансию %s", job_id, exc_info=True)
    return count
