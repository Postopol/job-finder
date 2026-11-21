from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from jobfinder.db import get_status, set_status, upsert_job
from jobfinder.web.app import create_app, review_links

from tests.conftest import mk


def seed(conn, hidden_reason=None, when=None, **kw) -> int:
    kw.setdefault("source_id", str(kw.get("title", "x")) + str(datetime.now().timestamp()))
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
    client.get(f"/jobs/{seeded}")
    assert get_status(conn, seeded) == "seen"


def test_status_change_persists(client, conn, seeded):
    r = client.post(f"/jobs/{seeded}/status", data={"status": "applied"})
    assert r.status_code == 200
    assert get_status(conn, seeded) == "applied"
    assert r.headers.get("HX-Trigger") == "list-changed"


def test_bad_status_rejected(client, seeded):
    assert client.post(f"/jobs/{seeded}/status", data={"status": "x"}).status_code == 422


def test_search_special_chars_no_500(client, seeded):
    for q in ['C++', '"', 'NEAR(', 'C#', '.NET', 'node.js', '*', '-']:
        assert client.get("/list", params={"q": q}).status_code == 200
        assert client.get("/", params={"q": q}).status_code == 200


def test_description_sanitized(client, conn):  # Review Focus 5
    jid = seed(conn, description_html='<p>ok</p><script>alert(1)</script>'
                                      '<img src=x onerror="alert(2)"><div>unclosed')
    html = client.get(f"/jobs/{jid}").text
    assert "<script>alert(1)" not in html and "onerror" not in html and "<p>ok</p>" in html


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
        assert client.get("/", params=params).status_code in (200, 422)
        assert client.get("/list", params=params).status_code in (200, 422)


def test_huge_job_id_404(client):
    assert client.get("/jobs/" + "9" * 30).status_code in (404, 422)
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
