from __future__ import annotations

import copy
import fcntl
import logging
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import db
from .filters import FilterConfig, classify_scope, hidden_reason
from .http import PoliteClient, SourceBlocked
from .models import Job
from .normalize import normalize_job
from .sources import REGISTRY
from .sources.base import Source

log = logging.getLogger(__name__)
_lock = threading.Lock()


@dataclass
class RunResult:
    source: str
    ok: bool
    fetched: int
    new: int
    skipped: int
    requests: int
    error: str | None


def _prepare(job: Job, cfg: FilterConfig) -> str | None:
    """Normalize in place, set scope/countries; return hidden_reason."""
    normalize_job(job)
    job.remote_scope, job.countries = classify_scope(job)
    return hidden_reason(job, cfg)


def _error_text(exc: Exception) -> str:
    if isinstance(exc, SourceBlocked):
        return f"сайт ограничил доступ (HTTP {exc.status})"
    return str(exc) or type(exc).__name__


def lock_path(db_path: Path | str) -> Path:
    return Path(f"{db_path}.collect.lock")


def db_file(conn) -> Path | None:
    """File of the connection's main database; None for in-memory/temporary DBs."""
    for row in conn.execute("PRAGMA database_list").fetchall():
        if row[1] == "main":
            return Path(row[2]) if row[2] else None
    return None


@contextmanager
def file_lock(db_path: Path | str | None) -> Iterator[bool]:
    """Cross-process collect lock (flock on `<db>.collect.lock`).

    Yields True when acquired (or there is no file to lock), False when another
    process or connection holds it.
    """
    if db_path is None:
        yield True
        return
    fd = os.open(lock_path(db_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def is_running(db_path: Path | str | None = None) -> bool:
    """True while a collect holds the thread lock here or the file lock of `db_path`."""
    if _lock.locked():
        return True
    if db_path is None:
        return False
    try:  # probe without creating the lock file
        fd = os.open(lock_path(db_path), os.O_RDWR)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def collect(conn, sources: dict[str, Source] | None = None,
            now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
            client_factory=PoliteClient, only: str | None = None) -> list[RunResult]:
    """Run sources one by one and store their jobs.

    Sources listed in the `disabled_sources` setting are skipped, except when
    `only` names one explicitly (a manual request runs even a disabled source).
    If another collect is already running (this process or another one on the
    same DB file), returns [] immediately.
    """
    if not _lock.acquire(blocking=False):
        return []
    try:
        with file_lock(db_file(conn)) as acquired:
            if not acquired:
                return []
            sources = REGISTRY if sources is None else sources
            if only is not None:
                names = [only] if only in sources else []
            else:
                disabled = set(db.get_setting(conn, "disabled_sources") or [])
                names = [n for n in sources if n not in disabled]
            return [_run_one(conn, sources[n], n, now_fn, client_factory) for n in names]
    finally:
        _lock.release()


def _run_one(conn, source: Source, name: str, now_fn, client_factory) -> RunResult:
    run_id = db.start_run(conn, name, now_fn())
    fetched = new = skipped = requests = 0
    error: str | None = None
    client = None
    try:
        client = client_factory()
        settings = db.all_settings(conn)
        before = copy.deepcopy(settings)
        cfg = FilterConfig(country=settings["country"], stopwords=settings["stopwords"])

        def wants(job: Job) -> bool:
            probe = copy.deepcopy(job)
            return _prepare(probe, cfg) is None

        jobs = source.fetch(client, db.known_source_ids(conn, name), wants, settings)
        fetched = len(jobs)
        for job in jobs:
            if not job.title or not job.url:
                skipped += 1
                continue
            try:
                reason = _prepare(job, cfg)
                _, is_new = db.upsert_job(conn, job, reason, now_fn())
            except Exception:
                log.warning("%s: не удалось сохранить вакансию %s", name, job.source_id, exc_info=True)
                skipped += 1
                continue
            new += is_new
        for key, value in settings.items():
            if key not in before or before[key] != value:
                db.set_setting(conn, key, value)
    except Exception as exc:
        error = _error_text(exc)
    finally:
        if client is not None:
            requests = getattr(client, "requests", 0)
            try:
                client.close()
            except Exception:
                log.warning("%s: ошибка закрытия клиента", name, exc_info=True)
    db.finish_run(conn, run_id, error is None, fetched, new, error, now_fn(), skipped=skipped)
    return RunResult(name, error is None, fetched, new, skipped, requests, error)
