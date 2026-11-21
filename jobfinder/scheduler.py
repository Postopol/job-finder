"""Background schedule: periodic collection and daily archive maintenance."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import archive, collector, db

log = logging.getLogger(__name__)

FIRST_COLLECT_DELAY = timedelta(seconds=10)
FIRST_MAINTENANCE_DELAY = timedelta(minutes=5)


def run_collect(db_path: Path | str) -> None:
    """One collection pass with its own connection; never raises."""
    conn = None
    try:
        conn = db.connect(db_path)
        results = collector.collect(conn)
        if not results:
            log.info("сбор пропущен: уже идёт или все источники выключены")
        for r in results:
            if r.ok:
                log.info("%s: получено %d, новых %d, пропущено %d, халал-фильтр −%d", r.source,
                         r.fetched, r.new, r.skipped, r.banned)
            else:
                log.warning("%s: ошибка: %s", r.source, r.error)
    except Exception:
        log.exception("сбор упал")
    finally:
        if conn is not None:
            conn.close()


def run_maintenance(db_path: Path | str) -> None:
    """archive_stale + purge_raw with its own connection; never raises."""
    conn = None
    try:
        conn = db.connect(db_path)
        now = datetime.now(UTC)
        archived = archive.archive_stale(conn, now)
        purged = archive.purge_raw(conn, now)
        log.info("обслуживание: в архив %d, очищено raw %d", archived, purged)
    except Exception:
        log.exception("обслуживание упало")
    finally:
        if conn is not None:
            conn.close()


def _interval(hours) -> IntervalTrigger:
    if not isinstance(hours, int) or isinstance(hours, bool) or not 1 <= hours <= 24:
        raise ValueError(f"interval_hours must be 1..24, got {hours!r}")
    return IntervalTrigger(hours=hours)


def start_scheduler(db_path: Path | str) -> BackgroundScheduler:
    """Start the scheduler: `collect` every interval_hours (first in 10 s), daily maintenance."""
    conn = db.connect(db_path)
    try:
        hours = db.get_setting(conn, "interval_hours")
    finally:
        conn.close()
    try:
        trigger = _interval(hours)
    except ValueError:
        log.warning("некорректный interval_hours=%r, беру %d", hours,
                    db.DEFAULT_SETTINGS["interval_hours"])
        trigger = _interval(db.DEFAULT_SETTINGS["interval_hours"])
    now = datetime.now(UTC)
    sched = BackgroundScheduler()
    common = dict(args=[db_path], max_instances=1, coalesce=True,
                  misfire_grace_time=None)  # a run missed during sleep fires once on wake
    sched.add_job(run_collect, trigger, id="collect", name="collect",
                  next_run_time=now + FIRST_COLLECT_DELAY, **common)
    sched.add_job(run_maintenance, IntervalTrigger(days=1), id="maintenance", name="maintenance",
                  next_run_time=now + FIRST_MAINTENANCE_DELAY, **common)
    sched.start()
    return sched


def reschedule(scheduler: BackgroundScheduler, hours: int) -> None:
    """Change the collect interval (Ruling R6); the next run is `hours` from now."""
    scheduler.reschedule_job("collect", trigger=_interval(hours))
