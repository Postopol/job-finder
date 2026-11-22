from __future__ import annotations

import copy
import json
import logging
import zlib
from datetime import datetime, timedelta

from . import db, halal
from .collector import _prepare
from .dedup import compatible
from .filters import FilterConfig, hidden_reason, stopword_reason
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


def purge_banned(conn, now: datetime) -> int:
    """Delete stored jobs the halal filter bans (kept if marked interesting/applied).

    Their postings go to the `banned` table so collects do not fetch them again.
    """
    rows = conn.execute(
        "SELECT j.id, j.title, j.company, j.description_text, COALESCE(s.status, 'new') AS st "
        "FROM jobs j LEFT JOIN user_status s ON s.job_id=j.id").fetchall()
    removed = 0
    for r in rows:
        if r["st"] in ("interesting", "applied"):
            continue
        reason = halal.banned_reason(Job(source="", source_id="", url="", title=r["title"],
                                         company=r["company"],
                                         description_text=r["description_text"] or ""))
        if reason is None:
            continue
        postings = conn.execute("SELECT source, source_id FROM postings WHERE job_id=?",
                                (r["id"],)).fetchall()
        for p in postings:
            db.add_banned(conn, p["source"], p["source_id"], reason, now)
        with db._tx(conn):
            conn.execute("DELETE FROM jobs_fts WHERE rowid=?", (r["id"],))
            conn.execute("DELETE FROM jobs WHERE id=?", (r["id"],))
        removed += 1
    if removed:
        log.info("халал-фильтр: удалено вакансий из базы: %d", removed)
    return removed


_SCALARS = ("company", "location_raw", "work_format", "seniority", "published_at")
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
        db.merge_salary(merged, vars(other))
        if len(other.description_html or "") > len(merged.description_html or ""):
            merged.description_html = other.description_html
            merged.description_text = other.description_text
    return merged


def _keep_description(old: dict, merged: Job, detail_source: bool) -> None:
    """Raw keeps only listing items, so a description loaded from a detail page cannot be
    re-parsed. Keep the stored description when the listing gives none, or when the stored
    one came from a detail page and the reparsed one is only a listing preview (Hirify
    tldr, hh snippet). Otherwise the reparsed description replaces it, even a shorter one.

    `detail_source`: one of the job's sources loads detail pages; used to guess for rows
    stored before descriptions were marked (the longer one is taken as the detail text)."""
    old_html = old["description_html"] or ""
    if not old_html:
        return
    flag = old.get("description_detail")
    from_detail = bool(flag) if flag is not None else (
        detail_source and len(old_html) > len(merged.description_html or ""))
    listing_empty = not (merged.description_html or merged.description_text)
    if listing_empty or (from_detail and not merged.description_detail):
        merged.description_html = old_html
        merged.description_text = old["description_text"]
        merged.description_detail = True if from_detail else flag


def _keep_existing(old: dict, merged: Job) -> None:
    """Some postings were not re-parsed: do not erase what they contributed."""
    for n in _SCALARS:
        if getattr(merged, n) is None and old[n] is not None:
            val = old[n]
            setattr(merged, n, datetime.fromisoformat(val) if n == "published_at" else val)
    for n in _LISTS:
        if not getattr(merged, n):
            setattr(merged, n, old[n])
    db.merge_salary(merged, old)


def reapply_stopwords(conn, stopwords: list[str] | None = None) -> int:
    """Re-check the stopword hide of every non-archived job from its stored text.

    Only rows hidden by a stopword or not hidden at all are touched, so other reasons stay.
    Returns the number of rows whose reason changed."""
    if stopwords is None:
        stopwords = db.get_setting(conn, "stopwords") or []
    rows = conn.execute(
        "SELECT id, title, description_text, hidden_reason FROM jobs WHERE archived_at IS NULL "
        "AND (hidden_reason IS NULL OR hidden_reason LIKE 'stopword:%')").fetchall()
    changes = []
    for r in rows:
        reason = stopword_reason(r["title"], r["description_text"], stopwords)
        if reason != r["hidden_reason"]:
            changes.append((reason, r["id"]))
    if changes:
        with db._tx(conn):
            conn.executemany("UPDATE jobs SET hidden_reason=? WHERE id=?", changes)
    return len(changes)


def recheck_unparsed(conn, cfg: FilterConfig, done: set[int]) -> int:
    """Visible jobs reparse could not rebuild (the source now skips the item, raw is gone):
    run the current filters on the stored fields and hide what they catch."""
    rows = conn.execute("SELECT * FROM jobs WHERE archived_at IS NULL AND hidden_reason IS NULL"
                        ).fetchall()
    changes = []
    for r in rows:
        if r["id"] in done:
            continue
        job = Job(source=r["source_primary"], source_id="", url=r["url"] or "", title=r["title"],
                  company=r["company"], location_raw=r["location_raw"],
                  work_format=r["work_format"], remote_scope=r["remote_scope"] or "unknown",
                  countries=json.loads(r["countries"] or "[]"),
                  description_text=r["description_text"] or "")
        reason = hidden_reason(job, cfg)
        if reason is not None:
            changes.append((reason, r["id"]))
    if changes:
        with db._tx(conn):
            conn.executemany("UPDATE jobs SET hidden_reason=? WHERE id=?", changes)
    return len(changes)


def _split_groups(parsed: list[tuple[int, Job]]) -> list[list[tuple[int, Job]]]:
    """Postings of one job grouped by compatible titles; the primary's group comes first."""
    groups: list[list[tuple[int, Job]]] = []
    for item in parsed:
        group = next((g for g in groups if compatible(g[0][1].title, item[1].title)), None)
        if group is None:
            groups.append([item])
        else:
            group.append(item)
    return groups


def reparse(conn, source: str | None = None, sources: dict[str, Source] | None = None) -> int:
    """Re-parse saved raw with current parsers, no network. Returns updated jobs count."""
    sources = REGISTRY if sources is None else sources
    settings = db.all_settings(conn)
    cfg = FilterConfig(country=settings["country"], stopwords=settings["stopwords"])
    query = ("SELECT p.id, p.job_id, p.source, p.raw FROM postings p JOIN jobs j ON j.id=p.job_id "
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
    done: set[int] = set()
    for job_id, posts in by_job.items():
        try:
            parsed: list[tuple[int, Job]] = []
            for r in posts:
                src = sources.get(r["source"])
                if src is None:
                    continue
                job = src.parse_item(json.loads(zlib.decompress(r["raw"])))
                if job is not None:
                    parsed.append((r["id"], job))
            if not parsed:
                continue
            groups = _split_groups(parsed)
            for group in groups[1:]:  # merged by mistake: each becomes its own job
                merged = _merge([j for _, j in group])
                db.split_off(conn, job_id, [pid for pid, _ in group], merged,
                             _prepare(merged, cfg))
                count += 1
            parsed = [j for _, j in groups[0]]
            done.add(job_id)
            merged = _merge(parsed)
            old = db.get_job(conn, job_id)
            job_sources = [p[0] for p in conn.execute(
                "SELECT source FROM postings WHERE job_id=?", (job_id,))]
            if len(parsed) < len(job_sources):
                _keep_existing(old, merged)
            detail_source = any(getattr(sources.get(n), "detail_pages", False) for n in job_sources)
            _keep_description(old, merged, detail_source)
            # filters run on the full description, as in collect
            db.update_job_fields(conn, job_id, merged, _prepare(merged, cfg))
            count += 1
        except Exception:
            log.warning("reparse: не удалось обработать вакансию %s", job_id, exc_info=True)
    # jobs without raw (or with a parser error) still get the current stopwords
    reapply_stopwords(conn, cfg.stopwords)
    recheck_unparsed(conn, cfg, done)
    return count
