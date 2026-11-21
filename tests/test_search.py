from datetime import timedelta

import pytest
from conftest import mk

from jobfinder.db import set_status, upsert_job
from jobfinder.normalize import normalize_job
from jobfinder.search import (SearchParams, count_sections, expand_query, search_jobs,
                              stem_text)

_n = 0


def add(conn, now=None, **kw) -> int:
    global _n
    from datetime import datetime, timezone
    now = now or datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    if "source_id" not in kw:
        _n += 1
        kw["source_id"] = f"auto{_n}"
        kw.setdefault("url", f"https://x/auto{_n}")
    hidden = kw.pop("hidden", None)
    job_id, _ = upsert_job(conn, normalize_job(mk(**kw)), hidden, now)
    return job_id


def titles(rows):
    return [r["title"] for r in rows]


def test_word_forms_ru(conn, now):
    add(conn, title="Python-разработчик")
    assert titles(search_jobs(conn, SearchParams(text="разработчика"), now)) == ["Python-разработчик"]


def test_synonyms(conn, now):
    add(conn, title="Senior Go Engineer", stack=["Kubernetes"])
    for q in ["голанг", "golang", "k8s", "старший"]:
        assert search_jobs(conn, SearchParams(text=q), now), q


@pytest.mark.parametrize("q", ['C++', 'C#', '.NET', 'node.js', '"', '*', '-', 'AND', 'NEAR(',
                               "'; DROP TABLE jobs;--", '+', '. . .', '""', '(a OR'])
def test_fts_special_input_never_raises(conn, now, q):
    add(conn, title="C++ developer")
    m = expand_query(q)
    if m:  # unguarded: a broken MATCH must fail the test
        conn.execute("SELECT rowid FROM jobs_fts WHERE jobs_fts MATCH ?", (m,)).fetchall()
    assert isinstance(search_jobs(conn, SearchParams(text=q), now), list)
    count_sections(conn, SearchParams(text=q), now)


@pytest.mark.parametrize("q", ["C++", "node.js", ".NET", "C#"])
def test_special_tech_hits(conn, now, q):
    add(conn, title="C++ developer", stack=["Node.js", ".NET", "C#"])
    assert titles(search_jobs(conn, SearchParams(text=q), now)) == ["C++ developer"]


def test_cplusplus_found(conn, now):
    add(conn, title="C++ developer")
    add(conn, title="C developer", source_id="2")
    assert titles(search_jobs(conn, SearchParams(text="C++"), now)) == ["C++ developer"]


def test_sections(conn, now):
    add(conn, title="A")
    b = add(conn, title="B", source_id="2")
    add(conn, title="C", source_id="3", hidden="restricted")
    set_status(conn, b, "rejected", now)
    assert titles(search_jobs(conn, SearchParams(), now)) == ["A"]
    assert set(titles(search_jobs(conn, SearchParams(section="hidden"), now))) == {"B", "C"}
    counts = count_sections(conn, SearchParams(), now)
    assert counts == {"feed": 1, "mine": 0, "archive": 0, "hidden": 2}


def test_mine_ignores_age(conn, now):
    a = add(conn, title="Old", source_id="1")
    set_status(conn, a, "applied", now)
    later = now + timedelta(days=30)
    assert titles(search_jobs(conn, SearchParams(section="mine"), later)) == ["Old"]
    assert search_jobs(conn, SearchParams(), later) == []


def test_salary_filter_uses_usd(conn, now):
    add(conn, title="RU", salary_raw="300 000 ₽")
    add(conn, title="EN", source_id="2", salary_raw="$1,000 / month")
    add(conn, title="None", source_id="3")
    p = SearchParams(salary_min_usd=2500, include_no_salary=False)
    assert titles(search_jobs(conn, p, now)) == ["RU"]
    p = SearchParams(salary_min_usd=2500, include_no_salary=True)
    assert set(titles(search_jobs(conn, p, now))) == {"RU", "None"}


def test_reindex_on_update(conn, now):
    add(conn, title="Python Developer", source_id="1")
    add(conn, title="Python Developer", source_id="1", description_text="rust")
    assert len(search_jobs(conn, SearchParams(text="python"), now)) == 1


def test_expand_query_shape():
    assert expand_query("") is None and expand_query("  --  ") is None
    q = expand_query("python senior")
    assert '"python"*' in q and " AND " in q and " OR " in q
    assert expand_query('a"b') == '"a"* AND "b"*'


def test_stem_text():
    assert "cplusplus" in stem_text("C++ dev").split()
    assert "dotnet" in stem_text(".NET dev").split()
    assert stem_text("team.") == "team"


def test_fts_backfill(conn, now):
    from jobfinder.search import ensure_fts
    add(conn, title="Rust Engineer")
    conn.execute("DROP TABLE jobs_fts")
    ensure_fts(conn)
    assert titles(search_jobs(conn, SearchParams(text="rust"), now)) == ["Rust Engineer"]
