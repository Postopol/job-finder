import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from jobfinder.http import PoliteClient
from jobfinder.sources import REGISTRY, hn, remotefirst, wwr
from jobfinder.sources.base import ParseError

FIX = Path(__file__).parent / "fixtures"


def text(name):
    return (FIX / name).read_text(encoding="utf-8")


def client(handler):
    return PoliteClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)


def first_job(mod, payload):
    for item in mod.parse_payload(payload):
        job = mod.SOURCE.parse_item(item)
        if job is not None:
            return job
    raise AssertionError("no job parsed")


CASES = [
    (wwr, lambda: text("wwr.rss"), "RSS"),
    (remotefirst, lambda: text("remotefirst.rss"), "RSS"),
    (hn, lambda: json.loads(text("hn_comments.json")), "Открытый API"),
]


@pytest.mark.parametrize("mod,payload,method", CASES)
def test_common(mod, payload, method):
    payload = payload()
    assert len(mod.parse_payload(payload)) >= 1
    job = first_job(mod, payload)
    assert job.title and job.source_id and job.url.startswith("https://")
    assert job.source == mod.SOURCE.name and job.lang == "en"
    assert job.raw is not None
    json.dumps(job.raw)
    assert job.published_at is not None and job.published_at.utcoffset() == timedelta(0)
    assert REGISTRY[mod.SOURCE.name] is mod.SOURCE
    assert mod.SOURCE.method == method and mod.SOURCE.full_listing is True


@pytest.mark.parametrize("mod", [wwr, remotefirst, hn])
def test_odd_items_return_none(mod):
    for item in ({}, {"title": None, "link": None}, {"objectID": "1", "comment_text": None},
                 {"title": "x", "link": 5, "comment_text": 7, "objectID": 3}):
        assert mod.SOURCE.parse_item(item) is None


# ---- wwr
def test_wwr_worldwide_and_company():
    payload = text("wwr.rss")
    items = wwr.parse_payload(payload)
    it = next(i for i in items if i["region"] == "Anywhere in the World"
              and i["category"].lower() in wwr.IT_CATEGORIES)
    job = wwr.SOURCE.parse_item(it)
    assert job.remote_scope == "worldwide"
    company, _, role = it["title"].partition(": ")
    assert job.company == company and job.title == role
    assert job.description_html.strip().startswith("<")
    assert wwr.SOURCE.parse_item({**it, "region": "USA Only"}).remote_scope == "restricted"
    assert wwr.SOURCE.parse_item({**it, "category": "Sales and Marketing"}) is None
    assert any(wwr.SOURCE.parse_item(i) is None for i in items)  # non-IT categories dropped


def test_wwr_not_a_feed():
    with pytest.raises(ParseError):
        wwr.parse_payload("<html><body>Cloudflare</body></html>")


def test_wwr_fetch():
    seen = []

    def h(req):
        seen.append(str(req.url))
        return httpx.Response(200, text=text("wwr.rss"))

    jobs = wwr.SOURCE.fetch(client(h), set(), lambda j: True, {})
    assert seen == [wwr.URL] and 10 < len(jobs) < 100


# ---- remotefirst
def test_remotefirst_company_split():
    job = first_job(remotefirst, text("remotefirst.rss"))
    assert job.url.startswith("https://remotefirstjobs.com/companies/")
    assert job.company and " at " not in job.title
    assert remotefirst.SOURCE.parse_item(
        {"title": "Dev at Foo Inc", "link": "https://remotefirstjobs.com/companies/foo/jobs/dev-1"}
    ).company == "Foo Inc"


def test_remotefirst_fetch_dedupes_by_link():
    seen = []

    def h(req):
        seen.append(req.url.path)
        return httpx.Response(200, text=text("remotefirst.rss"))

    jobs = remotefirst.SOURCE.fetch(client(h), set(), lambda j: True, {})
    assert seen == [f"/rss/jobs/{s}.rss" for s in remotefirst.SLUGS]
    assert len(jobs) == len(remotefirst.parse_payload(text("remotefirst.rss")))
    assert len({j.url for j in jobs}) == len(jobs)


# ---- hn
def test_hn_excludes_replies():
    payload = json.loads(text("hn_comments.json"))
    items = hn.parse_payload(payload)
    assert 0 < len(items) < len(payload["hits"])
    assert all(i["parent_id"] == i["story_id"] for i in items)


def test_hn_header_split():
    item = {"objectID": "123", "created_at_i": 1795268159, "story_id": 1, "parent_id": 1,
            "comment_text": "Acme | Backend Engineer | Remote (Global)<p>We build things &amp; more."}
    job = hn.SOURCE.parse_item(item)
    assert (job.company, job.title, job.location_raw) == ("Acme", "Backend Engineer",
                                                           "Remote (Global)")
    assert job.url == "https://news.ycombinator.com/item?id=123" and job.source_id == "123"
    assert job.remote_scope == "worldwide" and job.work_format == "remote"
    assert job.description_html == item["comment_text"]
    assert "We build things & more." in job.description_text
    assert hn.SOURCE.parse_item({**item, "comment_text": "Acme | Dev | Berlin<p>onsite"}) is None


def test_hn_latest_story():
    assert hn.latest_story_id(json.loads(text("hn_stories.json"))) == "50338728"
    with pytest.raises(ParseError):
        hn.latest_story_id({"hits": [{"title": "Ask HN: Who wants to be hired?"}]})


def _handler(seen):
    def h(req):
        seen.append(str(req.url))
        if "search_by_date" in req.url.path:
            return httpx.Response(200, text=text("hn_stories.json"))
        return httpx.Response(200, text=text("hn_comments.json"))
    return h


NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def test_hn_fetch_new_story_updates_settings():
    seen, settings = [], {"hn_last_story": "49922569", "hn_last_fetch": NOW.isoformat()}
    src = hn.HackerNews(now=lambda: NOW)
    jobs = src.fetch(client(_handler(seen)), set(), lambda j: True, settings)
    assert len(seen) == 2 and "story_50338728" in seen[1] and jobs
    assert settings["hn_last_story"] == "50338728"
    assert settings["hn_last_fetch"] == NOW.isoformat()


def test_hn_fetch_same_story_fresh_skips_comments():
    seen = []
    settings = {"hn_last_story": "50338728",
                "hn_last_fetch": (NOW - timedelta(hours=3)).isoformat()}
    src = hn.HackerNews(now=lambda: NOW)
    assert src.fetch(client(_handler(seen)), set(), lambda j: True, settings) == []
    assert len(seen) == 1
    assert settings["hn_last_fetch"] == (NOW - timedelta(hours=3)).isoformat()


def test_hn_fetch_same_story_stale_refetches():
    seen = []
    settings = {"hn_last_story": "50338728",
                "hn_last_fetch": (NOW - timedelta(hours=30)).isoformat()}
    jobs = hn.HackerNews(now=lambda: NOW).fetch(client(_handler(seen)), set(), lambda j: True,
                                                settings)
    assert len(seen) == 2 and jobs
    assert settings["hn_last_fetch"] == NOW.isoformat()


def test_hn_fetch_first_run_without_settings():
    seen, settings = [], {}
    jobs = hn.HackerNews(now=lambda: NOW).fetch(client(_handler(seen)), set(), lambda j: True,
                                                settings)
    assert len(seen) == 2 and jobs and settings["hn_last_story"] == "50338728"


def _reasons(mod, payload):
    from jobfinder.filters import FilterConfig, hidden_reason
    jobs = [j for j in map(mod.SOURCE.parse_item, mod.parse_payload(payload)) if j]
    return {j.title: hidden_reason(j, FilterConfig()) for j in jobs}


def test_remotefirst_non_it_hidden():
    r = _reasons(remotefirst, text("remotefirst.rss"))
    for t in ("CAAS Staff Accountant", "Senior Proposal Consultant", "Go-to-Market Media Specialist",
              "Community Manager", "Sales Development Representative - Remote"):
        assert r[t] == "non_it", t
    for t in ("Senior iOS Engineer", "Software Engineer", "Analytics Engineer"):
        assert r[t] is None, t


def test_wwr_non_it_hidden():
    r = _reasons(wwr, text("wwr.rss"))
    assert r["Manager, Sales Compensation"] == "non_it"
    assert r["Associate Manager, SOX and Internal Controls"] == "non_it"
    assert r["Senior Platform Engineer"] is None and r["Machine Learning Engineer"] is None
