import itertools
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from jobfinder import collector, scheduler
from jobfinder.db import (
    finish_run,
    get_setting,
    get_status,
    set_setting,
    set_status,
    start_run,
    upsert_job,
)
from jobfinder.sources import REGISTRY
from jobfinder.web.app import create_app, review_links
from tests.conftest import mk

_ids = itertools.count(1000)


def seed(conn, hidden_reason=None, when=None, **kw) -> int:
    kw.setdefault("source_id", f"seed-{next(_ids)}")
    jid, _ = upsert_job(conn, mk(**kw), hidden_reason, when or datetime.now(UTC))
    return jid


@pytest.fixture
def client(tmp_path, conn):
    with TestClient(create_app(tmp_path / "j.db", start_scheduler=False)) as c:
        yield c


@pytest.fixture
def seeded(conn):
    return seed(conn, source="himalayas", source_id="1", title="Python Developer",
                company="Northwind Labs", url="https://himalayas.app/jobs/1",
                salary_raw="$5000-6500", salary_min=5000, salary_max=6500,
                salary_currency="USD", salary_period="month",
                remote_scope="worldwide", stack=["Python", "FastAPI"],
                description_text="Line one\nLine two")


# --- brief tests ------------------------------------------------------------

def test_feed_renders_jobs(client, seeded):
    assert "Python Developer" in client.get("/").text


def test_open_marks_seen(client, conn, seeded):
    r = client.get(f"/jobs/{seeded}")
    assert get_status(conn, seeded) == "seen"
    assert r.headers.get("HX-Trigger-After-Swap") == "list-changed"
    assert "HX-Trigger-After-Swap" not in client.get(f"/jobs/{seeded}").headers  # already seen


def test_status_change_persists(client, conn, seeded):
    r = client.post(f"/jobs/{seeded}/status", data={"status": "applied"})
    assert r.status_code == 200
    assert get_status(conn, seeded) == "applied"
    # after-swap, so the list refresh sees the job id updated by the OOB swap
    assert r.headers.get("HX-Trigger-After-Swap") == "list-changed"
    assert "HX-Trigger" not in r.headers


def test_bad_status_rejected(client, seeded):
    assert client.post(f"/jobs/{seeded}/status", data={"status": "x"}).status_code == 422


def test_search_special_chars_no_500(client, seeded):
    for q in ['C++', '"', 'NEAR(', 'C#', '.NET', 'node.js', '*', '-']:
        assert client.get("/list", params={"q": q}).status_code == 200
        assert client.get("/", params={"q": q}).status_code == 200


def test_description_sanitized(client, conn):  # Review Focus 5
    jid = seed(conn, description_html='<p>ok</p><script>alert(1)</script>'
                                      '<img src=x onerror="alert(2)"><div>unclosed'
                                      '<a href="javascript:alert(3)">js</a>'
                                      '<a href="https://ok.example/x" onclick="alert(4)">ok</a>'
                                      '<span hx-get="/jobs/1/status" hx-trigger="load">htmx</span>')
    html = client.get(f"/jobs/{jid}").text
    assert "<script>alert(1)" not in html and "onerror" not in html and "<p>ok</p>" in html
    assert "javascript:" not in html and "onclick" not in html
    assert 'hx-trigger="load"' not in html and 'hx-get="/jobs/1/status"' not in html
    assert 'href="https://ok.example/x"' in html
    link = html[html.index('href="https://ok.example/x"') - 200:html.index(">ok</a>")]
    assert 'target="_blank"' in link and "noopener" in link
    assert '<div class="prose" hx-disable>' in html


def test_non_http_urls_not_linked(client, conn):
    jid = seed(conn, source="himalayas", url="javascript:alert(1)", title="Evil", company="E")
    html = client.get(f"/jobs/{jid}").text
    assert "javascript:" not in html
    assert "Himalayas" in html  # source still named, as plain text


def test_csrf_foreign_origin_rejected(client, conn, seeded):
    r = client.post(f"/jobs/{seeded}/status", data={"status": "applied"},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and get_status(conn, seeded) == "new"
    r = client.post(f"/jobs/{seeded}/status", data={"status": "applied"},
                    headers={"Referer": "https://evil.example/page"})
    assert r.status_code == 403
    r = client.post(f"/jobs/{seeded}/status", data={"status": "applied"},
                    headers={"Origin": "null"})
    assert r.status_code == 403
    assert get_status(conn, seeded) == "new"


def test_csrf_same_origin_allowed(client, conn, seeded):
    r = client.post(f"/jobs/{seeded}/status", data={"status": "interesting"},
                    headers={"Origin": "http://testserver"})
    assert r.status_code == 200 and get_status(conn, seeded) == "interesting"
    r = client.post(f"/jobs/{seeded}/status", data={"status": "applied"},
                    headers={"Referer": "http://testserver/?job=1"})
    assert r.status_code == 200 and get_status(conn, seeded) == "applied"


def test_csrf_localhost_port_must_match():
    from starlette.requests import Request

    from jobfinder.web.app import origin_allowed

    def req(host):
        return Request({"type": "http", "method": "POST", "path": "/", "query_string": b"",
                        "scheme": "http", "server": ("127.0.0.1", 8000),
                        "headers": [(b"host", host.encode())]})
    assert origin_allowed(req("127.0.0.1:8000"), "http://127.0.0.1:8000")
    assert origin_allowed(req("127.0.0.1:8000"), "http://localhost:8000")
    assert not origin_allowed(req("127.0.0.1:8000"), "http://127.0.0.1:9999")
    assert not origin_allowed(req("evil.example:8000"), "http://evil.example:8000")  # rebinding


def test_review_links_encode_company():
    links = review_links("Northwind Labs")
    assert "Northwind%20Labs" in links[0]["href"]
    assert [link["label"] for link in links] == [
        "Glassdoor", "Dreamjob", "Хабр Карьера", "Google", "Reddit"]


def test_unknown_job_404(client):
    assert client.get("/jobs/999999").status_code == 404
    assert client.post("/jobs/999999/status", data={"status": "seen"}).status_code == 404
    assert client.get("/", params={"job": 999999}).status_code == 404


# --- extra coverage -----------------------------------------------------------

def test_detail_shows_fields_and_links(client, conn, seeded):
    seed(conn, source="remoteok", source_id="r1", title="Python Developer",
         company="Northwind Labs", url="https://remoteok.com/1", remote_scope="worldwide",
         stack=["Python", "FastAPI"], description_text="Line one\nLine two")  # merged posting
    html = client.get(f"/jobs/{seeded}").text
    assert "Открыть на Himalayas" in html
    assert 'href="https://himalayas.app/jobs/1"' in html
    assert 'href="https://remoteok.com/1"' in html
    assert "весь мир" in html
    assert "FastAPI" in html
    assert "Northwind%20Labs" in html and 'rel="noopener"' in html
    assert "Line one<br>" in html or "Line one<br />" in html
    for label in ("Посмотрел", "Интересно", "Откликнулся", "Не подходит"):
        assert label in html


def test_detail_text_description_escaped(client, conn):
    jid = seed(conn, description_text="<b>bold</b>")
    html = client.get(f"/jobs/{jid}").text
    assert "&lt;b&gt;bold&lt;/b&gt;" in html


def test_salary_missing_and_scope_labels(client, conn):
    a = seed(conn, title="Go Dev", company="A", remote_scope="countries", countries=["KZ", "RU"])
    b = seed(conn, title="Rust Dev", company="B", remote_scope="unknown")
    c = seed(conn, title="Java Dev", company="C", remote_scope="cis")
    html_a = client.get(f"/jobs/{a}").text
    assert "не указана" in html_a and "страны: KZ, RU" in html_a
    assert "уточнить" in client.get(f"/jobs/{b}").text
    assert "СНГ" in client.get(f"/jobs/{c}").text


def test_hidden_section_shows_reason(client, conn):
    jid = seed(conn, title="Hybrid Dev", company="H", hidden_reason="hybrid")
    feed = client.get("/list").text
    assert "Hybrid Dev" not in feed
    hidden = client.get("/list", params={"section": "hidden"}).text
    assert "Hybrid Dev" in hidden and "гибрид" in hidden
    assert "гибрид" in client.get(f"/jobs/{jid}").text


def test_hidden_non_it_has_russian_label(client, conn):
    jid = seed(conn, title="Account Executive", company="S", hidden_reason="non_it")
    hidden = client.get("/list", params={"section": "hidden"}).text
    assert "не IT" in hidden and "non_it" not in hidden
    assert "не IT" in client.get(f"/jobs/{jid}").text


def test_tabs_with_counts(client, conn, seeded):
    other = seed(conn, title="Go Dev", company="G")
    set_status(conn, other, "interesting", datetime.now(UTC))
    html = client.get("/").text
    for label in ("Лента", "Мои", "Архив", "Скрытые"):
        assert label in html
    assert "Мои · 1" in html and "Лента · 2" in html


def test_filters_map_to_search(client, conn, seeded):
    seed(conn, source="hh", title="Go Dev", company="G", lang="ru", remote_scope="cis")
    r = client.get("/list", params={"src": "hh"}).text
    assert "Go Dev" in r and "Python Developer" not in r
    r = client.get("/list", params={"lang": "en"}).text
    assert "Python Developer" in r and "Go Dev" not in r
    r = client.get("/list", params={"scope": ["worldwide", "unknown"]}).text
    assert "Python Developer" in r and "Go Dev" not in r
    r = client.get("/list", params={"salary": "3000", "nosalary": "0"}).text  # unchecked
    assert "Python Developer" in r and "Go Dev" not in r
    r = client.get("/list", params={"salary": "3000", "nosalary": ["0", "1"]}).text
    assert "Go Dev" in r
    r = client.get("/list", params={"src": ""}).text  # form with every source unchecked
    assert "Python Developer" not in r and "Go Dev" not in r
    r = client.get("/list", params={"q": "python"}).text
    assert "Python Developer" in r and "Go Dev" not in r


def test_fresh_filter(client, conn):
    seed(conn, title="Old Job", company="O", when=datetime.now(UTC) - timedelta(days=5))
    assert "Old Job" not in client.get("/list").text  # default fresh_days=3
    assert "Old Job" in client.get("/list", params={"fresh": "7"}).text


def test_bad_query_values_do_not_500(client, seeded):
    huge = "9" * 30
    for params in ({"salary": "abc"}, {"fresh": "x"}, {"section": "nope"}, {"job": "abc"},
                   {"salary": huge}, {"fresh": huge}, {"fresh": "-5"}, {"job": huge}):
        assert client.get("/", params=params).status_code == 200
        assert client.get("/list", params=params).status_code == 200


def test_huge_job_id_404(client):
    assert client.get("/jobs/" + "9" * 30).status_code == 404
    assert client.post("/jobs/" + "9" * 20 + "/status", data={"status": "seen"}).status_code == 404


def test_list_shows_country_codes(client, conn):
    seed(conn, title="Go Dev", company="A", remote_scope="countries", countries=["KZ", "RU"])
    assert "страны: KZ, RU" in client.get("/list").text


def test_deep_link_opens_job(client, conn, seeded):
    html = client.get("/", params={"job": seeded}).text
    assert "Открыть на Himalayas" in html
    assert get_status(conn, seeded) == "seen"


def test_static_served(client):
    assert client.get("/static/htmx.min.js").status_code == 200
    css = client.get("/static/style.css")
    assert css.status_code == 200 and "#a970ff" in css.text


# --- triage (screen C) ----------------------------------------------------------

@pytest.fixture
def seeded2(conn):
    now = datetime.now(UTC)
    j1 = seed(conn, source="himalayas", title="Python Developer", company="Northwind Labs",
              url="https://himalayas.app/jobs/p1", remote_scope="worldwide",
              salary_min=5000, salary_max=6500, salary_currency="USD", salary_period="month",
              seniority="senior", stack=["Python", "FastAPI"],
              description_html="<p>Build APIs</p><script>alert(1)</script>",
              when=now - timedelta(hours=5))
    j2 = seed(conn, source="hh", title="Go Developer", company="Квадрат Софт", lang="ru",
              url="https://hh.ru/vacancy/2", remote_scope="cis", when=now - timedelta(hours=1))
    return j1, j2


def test_triage_shows_new_and_advances(client, conn, seeded2):
    j1, j2 = seeded2
    first = client.get("/triage").text
    assert "Python Developer" in first  # oldest first
    assert "$5\u00a0000–6\u00a0500 / мес" in first and "Senior" in first and "весь мир" in first
    assert "FastAPI" in first and "<p>Build APIs</p>" in first and "<script>alert(1)" not in first
    assert 'hx-disable' in first
    assert 'href="https://himalayas.app/jobs/p1"' in first and "Northwind%20Labs" in first
    assert "0 из 2" in first
    assert "Go Developer" in first  # «следующая» hint
    for label in ("Не подходит", "Позже", "Интересно", "keys.js"):
        assert label in first
    r = client.post(f"/triage/{j1}", data={"action": "interesting"}, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert get_status(conn, j1) == "interesting" and "Go Developer" in r.text
    assert "1 из 2" in r.text
    r = client.post(f"/triage/{j2}", data={"action": "reject"}, headers={"HX-Request": "true"})
    assert get_status(conn, j2) == "rejected"
    assert "Новых вакансий нет" in r.text and "2 из 2" in r.text


def test_triage_later_is_seen(client, conn, seeded2):
    j1, _ = seeded2
    client.post(f"/triage/{j1}", data={"action": "later"})
    assert get_status(conn, j1) == "seen"
    assert "Python Developer" not in client.get("/triage").text.split("Следующая")[0]


def test_triage_skips_hidden_archived_and_decided(client, conn):
    seed(conn, title="Hybrid Dev", company="H", hidden_reason="hybrid")
    done = seed(conn, title="Done Dev", company="D")
    set_status(conn, done, "applied", datetime.now(UTC))
    old = seed(conn, title="Archived Dev", company="A")
    conn.execute("UPDATE jobs SET archived_at=? WHERE id=?", (datetime.now(UTC).isoformat(), old))
    conn.commit()
    assert "Новых вакансий нет" in client.get("/triage").text


def test_triage_empty_state(client, conn):
    assert "Новых вакансий нет" in client.get("/triage").text


def test_triage_stale_tab_does_not_overwrite(client, conn, seeded2):
    j1, j2 = seeded2
    set_status(conn, j1, "applied", datetime.now(UTC))  # decided elsewhere meanwhile
    r = client.post(f"/triage/{j1}", data={"action": "reject"}, headers={"HX-Request": "true"})
    assert r.status_code == 200 and get_status(conn, j1) == "applied"
    assert "Go Developer" in r.text  # just the next card


def test_triage_buttons_all_disabled_while_posting(client, seeded2):
    html = client.get("/triage").text
    assert 'hx-disabled-elt=".triage-actions button"' in html
    assert 'id="triage-progress" class="progress" aria-live="polite"' in html
    assert 'id="triage" class="triage">' in html


def test_triage_post_errors(client, conn, seeded2):
    j1, _ = seeded2
    assert client.post("/triage/999999", data={"action": "later"}).status_code == 404
    assert client.post(f"/triage/{j1}", data={"action": "applied"}).status_code == 422
    assert get_status(conn, j1) == "new"


def test_triage_without_htmx_redirects(client, conn, seeded2):
    j1, _ = seeded2
    r = client.post(f"/triage/{j1}", data={"action": "later"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/triage"


def test_keys_js_served(client):
    js = client.get("/static/keys.js")
    assert js.status_code == 200 and "ArrowLeft" in js.text and "ArrowDown" in js.text


# --- sources & settings (screen D) ------------------------------------------------

def test_sources_page_lists_registry(client):
    html = client.get("/sources").text
    assert all(n in html for n in REGISTRY)
    assert "Открытый API" in html and "Обновить все" in html and "Настройки сбора" in html


def test_sources_page_shows_last_error(client, conn):
    now = datetime.now(UTC)
    run = start_run(conn, "remoteok", now)
    finish_run(conn, run, False, 0, 0, "HTTP 429", now)
    run = start_run(conn, "jobicy", now)
    finish_run(conn, run, True, 40, 7, None, now, skipped=12)
    html = client.get("/sources").text
    assert "HTTP 429" in html
    assert "пропущено 12" in html


def test_sources_page_ok_run_with_block_note(client, conn):
    now = datetime.now(UTC)
    run = start_run(conn, "hirify", now)
    finish_run(conn, run, True, 20, 20, "сайт ограничил доступ (HTTP 429), остальное — в следующий сбор", now)
    html = client.get("/sources").text
    assert "работает · сайт ограничил доступ (HTTP 429)" in html


def test_sources_page_disabled_state(client, conn):
    set_setting(conn, "disabled_sources", ["wwr"])
    assert "выключен" in client.get("/sources").text


def test_toggle_source(client, conn):
    r = client.post("/sources/remoteok/toggle")
    assert r.status_code == 200 and "выключен" in r.text
    assert "remoteok" in get_setting(conn, "disabled_sources")
    client.post("/sources/remoteok/toggle")
    assert "remoteok" not in get_setting(conn, "disabled_sources")
    assert client.post("/sources/nope/toggle").status_code == 404


def test_settings_validation(client, conn):
    assert client.post("/settings", data={"interval_hours": "0"}).status_code == 422
    r = client.post("/settings", data={"interval_hours": "25"})
    assert r.status_code == 422 and "от 1 до 24" in r.text
    assert client.post("/settings", data={"interval_hours": "abc"}).status_code == 422
    assert client.post("/settings", data={"fresh_days": "31"}).status_code == 422
    assert client.post("/settings", data={"fresh_days": "0"}).status_code == 422
    assert get_setting(conn, "interval_hours") == 6 and get_setting(conn, "fresh_days") == 3


def test_settings_saved(client, conn):
    r = client.post("/settings", data={"interval_hours": "3", "fresh_days": "7",
                                       "stopwords": " 1С, PHP ,, офис\n", "hh_token": ""})
    assert r.status_code == 200
    assert get_setting(conn, "interval_hours") == 3 and get_setting(conn, "fresh_days") == 7
    assert get_setting(conn, "stopwords") == ["1С", "PHP", "офис"]
    assert get_setting(conn, "hh_token") == ""


def test_hh_token_kept_cleared_and_not_echoed(client, conn):
    client.post("/settings", data={"hh_token": "SECRET-TOKEN-123"})
    assert get_setting(conn, "hh_token") == "SECRET-TOKEN-123"
    page = client.get("/sources").text
    assert "SECRET-TOKEN-123" not in page and "задан" in page
    r = client.post("/settings", data={"hh_token": "", "interval_hours": "6"})
    assert "SECRET-TOKEN-123" not in r.text
    assert get_setting(conn, "hh_token") == "SECRET-TOKEN-123"  # empty keeps
    client.post("/settings", data={"hh_token": "", "hh_token_clear": "1"})
    assert get_setting(conn, "hh_token") == ""


class FakeSched:
    class Job:
        next_run_time = datetime.now(UTC) + timedelta(hours=2)

    def get_job(self, job_id):
        return self.Job() if job_id == "collect" else None

    def shutdown(self, wait=True):
        pass


def test_settings_reschedules_running_scheduler(client, conn, monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler, "reschedule", lambda s, h: calls.append(h))
    client.app.state.scheduler = FakeSched()
    client.post("/settings", data={"interval_hours": "6"})
    assert calls == []  # unchanged
    client.post("/settings", data={"interval_hours": "12"})
    assert calls == [12]


def test_collect_starts_background(client, monkeypatch):
    import threading
    started = threading.Event()
    monkeypatch.setattr(scheduler, "run_collect", lambda path: started.set())
    r = client.post("/collect")
    assert r.status_code == 200 and "Сбор запущен" in r.text
    assert started.wait(2)


def test_collect_already_running(client, monkeypatch):
    monkeypatch.setattr(scheduler, "run_collect", lambda path: pytest.fail("must not start"))
    assert collector._lock.acquire(blocking=False)
    try:
        assert "Сбор уже идёт" in client.post("/collect").text
    finally:
        collector._lock.release()


def test_collect_already_running_other_process(client, tmp_path, monkeypatch):
    import fcntl
    import os
    monkeypatch.setattr(scheduler, "run_collect", lambda path: pytest.fail("must not start"))
    fd = os.open(f"{tmp_path / 'j.db'}.collect.lock", os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert "Сбор уже идёт" in client.post("/collect").text
    finally:
        os.close(fd)


def test_new_posts_reject_foreign_origin(client, conn, seeded2, monkeypatch):
    monkeypatch.setattr(scheduler, "run_collect", lambda path: None)
    evil = {"Origin": "https://evil.example"}
    j1, _ = seeded2
    assert client.post(f"/triage/{j1}", data={"action": "later"}, headers=evil).status_code == 403
    assert client.post("/sources/remoteok/toggle", headers=evil).status_code == 403
    assert client.post("/settings", data={"interval_hours": "3"}, headers=evil).status_code == 403
    assert client.post("/collect", headers=evil).status_code == 403
    assert get_status(conn, j1) == "new" and get_setting(conn, "interval_hours") == 6
    assert get_setting(conn, "disabled_sources") == []


def test_sources_shows_schedule_when_running(client, conn):
    run = start_run(conn, "jobicy", datetime.now(UTC))
    finish_run(conn, run, True, 1, 1, None, datetime.now(UTC))
    client.app.state.scheduler = FakeSched()
    html = client.get("/sources").text
    assert "Последний сбор" in html and "следующий в" in html
