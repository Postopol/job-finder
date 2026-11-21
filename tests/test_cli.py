from pathlib import Path

import pytest

from jobfinder import cli
from jobfinder.db import connect, last_runs
from jobfinder.sources.base import Source
from tests.conftest import mk


class FakeClient:
    def __init__(self, *a, **kw):
        self.requests = 2

    def close(self):
        pass


class FakeSource(Source):
    lang = "en"
    full_listing = True
    method = "test"

    def __init__(self, name, fail=False):
        self.name = name
        self.fail = fail
        self.seen_settings = None

    def parse_item(self, item):
        return None

    def fetch(self, client, known, wants, settings):
        self.seen_settings = settings
        if self.fail:
            raise RuntimeError("сломалось")
        settings["max_pages"] = 99  # sources may mutate settings; must not persist here
        return [mk(source=self.name, source_id="a", url="https://f/a"),
                mk(source=self.name, source_id="b", url="https://f/b", title="Go Dev"),
                mk(source=self.name, source_id="c", url="", title="No url")]


@pytest.fixture
def fake(monkeypatch):
    sources = {"fake": FakeSource("fake"), "broken": FakeSource("broken", fail=True)}
    monkeypatch.setattr(cli, "REGISTRY", sources)
    monkeypatch.setattr(cli, "PoliteClient", FakeClient)
    return sources


def test_cli_collect_prints_per_source(fake, capsys, tmp_path):
    db = tmp_path / "x.db"
    assert cli.main(["collect", "--db", str(db)]) == 0
    out = capsys.readouterr().out.splitlines()
    fake_line = next(line for line in out if line.startswith("fake"))
    assert "ok" in fake_line and "получено 3" in fake_line and "новых 2" in fake_line
    assert "пропущено 1" in fake_line and "запросов 2" in fake_line
    broken_line = next(line for line in out if line.startswith("broken"))
    assert "ошибка" in broken_line and "сломалось" in broken_line
    assert set(last_runs(connect(db))) == {"fake", "broken"}


def test_cli_collect_single_source(fake, capsys, tmp_path):
    assert cli.main(["collect", "--source", "fake", "--db", str(tmp_path / "x.db")]) == 0
    out = capsys.readouterr().out
    assert "fake" in out and "broken" not in out


def test_cli_unknown_source_exit_2(fake, capsys, tmp_path):
    db = tmp_path / "x.db"
    for cmd in ("collect", "check-sources", "reparse"):
        assert cli.main([cmd, "--source", "nope", "--db", str(db)]) == 2
        assert "nope" in capsys.readouterr().err
    assert not db.exists()


def test_check_sources_writes_nothing(fake, capsys, tmp_path):
    db = tmp_path / "absent" / "x.db"
    assert cli.main(["check-sources", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "fake" in out and "3" in out
    assert "broken" in out and "сломалось" in out
    assert not db.exists() and not db.parent.exists()
    assert fake["fake"].seen_settings["max_pages"] == 99  # its own copy, started at 1


def test_check_sources_uses_existing_settings_readonly(fake, capsys, tmp_path):
    db = tmp_path / "x.db"
    conn = connect(db)
    conn.execute("INSERT INTO settings(key, value) VALUES('hh_token', '\"T\"')")
    conn.commit()
    conn.close()
    assert cli.main(["check-sources", "--source", "fake", "--db", str(db)]) == 0
    s = fake["fake"].seen_settings
    assert s["hh_token"] == "T"
    conn = connect(db)
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    assert conn.execute("SELECT value FROM settings WHERE key='max_pages'").fetchone() is None


def test_check_sources_max_pages_one(monkeypatch, capsys, tmp_path):
    seen = {}

    class Probe(FakeSource):
        def fetch(self, client, known, wants, settings):
            seen.update(max_pages=settings["max_pages"], known=known, wants=wants(None))
            return []
    monkeypatch.setattr(cli, "REGISTRY", {"p": Probe("p")})
    monkeypatch.setattr(cli, "PoliteClient", FakeClient)
    cli.main(["check-sources", "--db", str(tmp_path / "x.db")])
    assert seen == {"max_pages": 1, "known": set(), "wants": True}


def test_cli_reparse_prints_count(fake, capsys, tmp_path):
    assert cli.main(["reparse", "--db", str(tmp_path / "x.db")]) == 0
    assert "0" in capsys.readouterr().out


def test_default_db_path_is_project_root():
    path = cli.default_db_path()
    assert path == Path(cli.__file__).resolve().parent.parent / "data" / "jobs.db"
    assert (path.parent.parent / "pyproject.toml").exists()
