from datetime import datetime, timedelta

import pytest

from jobfinder import scheduler
from jobfinder.db import set_setting


@pytest.fixture
def no_jobs(monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler, "run_collect", lambda path: calls.append("collect"))
    monkeypatch.setattr(scheduler, "run_maintenance", lambda path: calls.append("maint"))
    return calls


def test_start_registers_jobs_and_stops(tmp_path, conn, no_jobs):
    set_setting(conn, "interval_hours", 4)
    s = scheduler.start_scheduler(tmp_path / "j.db")
    try:
        assert s.running
        collect = s.get_job("collect")
        assert collect.trigger.interval == timedelta(hours=4)
        lead = collect.next_run_time - datetime.now(collect.next_run_time.tzinfo)
        assert timedelta(seconds=0) < lead <= timedelta(seconds=11)
        assert s.get_job("maintenance").trigger.interval == timedelta(days=1)
        assert collect.misfire_grace_time is None and collect.coalesce
    finally:
        s.shutdown(wait=False)
    assert not s.running
    assert no_jobs == []


def test_reschedule(tmp_path, conn, no_jobs):
    s = scheduler.start_scheduler(tmp_path / "j.db")
    try:
        scheduler.reschedule(s, 3)
        assert s.get_job("collect").trigger.interval == timedelta(hours=3)
        with pytest.raises(ValueError):
            scheduler.reschedule(s, 0)
    finally:
        s.shutdown(wait=False)


def test_jobs_never_raise(tmp_path, monkeypatch, caplog):
    def boom(*a, **kw):
        raise RuntimeError("kaput")
    monkeypatch.setattr(scheduler.collector, "collect", boom)
    monkeypatch.setattr(scheduler.archive, "archive_stale", boom)
    monkeypatch.setattr(scheduler.profile, "refresh", boom)
    scheduler.run_collect(tmp_path / "j.db")
    scheduler.run_maintenance(tmp_path / "j.db")
    assert "kaput" in caplog.text


def test_maintenance_runs_archive_and_purge(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler.archive, "archive_stale",
                        lambda conn, now: calls.append("a") or 0)
    monkeypatch.setattr(scheduler.archive, "purge_raw", lambda conn, now: calls.append("p") or 0)
    scheduler.run_maintenance(tmp_path / "j.db")
    assert calls == ["a", "p"]


def test_collect_refreshes_resume_first(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler.profile, "refresh_quietly",
                        lambda conn, now: calls.append("resume") or True)
    monkeypatch.setattr(scheduler.collector, "collect", lambda conn: calls.append("collect") or [])
    scheduler.run_collect(tmp_path / "j.db")
    assert calls == ["resume", "collect"]
