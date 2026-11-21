from __future__ import annotations

import json
import zlib
from datetime import datetime, timedelta

from . import db
from .collector import _prepare
from .filters import FilterConfig
from .sources import REGISTRY
from .sources.base import Source

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


def reparse(conn, source: str | None = None, sources: dict[str, Source] | None = None) -> int:
    """Re-parse saved raw with current parsers, no network. Returns updated jobs count."""
    sources = REGISTRY if sources is None else sources
    settings = db.all_settings(conn)
    cfg = FilterConfig(country=settings["country"], stopwords=settings["stopwords"])
    query = "SELECT job_id, source, raw FROM postings WHERE raw IS NOT NULL"
    args: tuple = ()
    if source is not None:
        query += " AND source=?"
        args = (source,)
    updated: set[int] = set()
    for r in conn.execute(query + " ORDER BY id", args).fetchall():
        src = sources.get(r["source"])
        if src is None or r["job_id"] in updated:
            continue
        job = src.parse_item(json.loads(zlib.decompress(r["raw"])))
        if job is None:
            continue
        reason = _prepare(job, cfg)
        db.update_job_fields(conn, r["job_id"], job, reason)
        updated.add(r["job_id"])
    return len(updated)
