import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from jobfinder.http import PoliteClient
from jobfinder.sources import REGISTRY, himalayas, jobicy, remoteok, workingnomads

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def client(handler):
    return PoliteClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)


def first_job(mod, payload):
    for item in mod.parse_payload(payload):
        job = mod.SOURCE.parse_item(item)
        if job is not None:
            return job
    raise AssertionError("no job parsed")


CASES = [
    (himalayas, "himalayas.json"),
    (remoteok, "remoteok.json"),
    (jobicy, "jobicy.json"),
    (workingnomads, "workingnomads.json"),
]


@pytest.mark.parametrize("mod,fixture", CASES)
def test_common(mod, fixture):
    payload = load(fixture)
    items = mod.parse_payload(payload)
    assert len(items) >= 1
    job = first_job(mod, payload)
    assert job.title and job.source_id and job.url.startswith("https://")
    assert job.source == mod.SOURCE.name and job.lang == "en"
    assert job.raw is not None
    json.dumps(job.raw)
    assert job.published_at is not None and job.published_at.utcoffset() == timedelta(0)
    assert REGISTRY[mod.SOURCE.name] is mod.SOURCE
    assert mod.SOURCE.method == "Открытый API"


def test_himalayas_worldwide():
    payload = load("himalayas.json")
    job = first_job(himalayas, payload)
    assert job.remote_scope == "worldwide"
    assert job.salary_min == 2000 and job.salary_max == 3000
    assert job.salary_currency == "USD" and job.salary_period == "month"
    assert job.timezones == ["UTC+3.5"]
    assert himalayas.SOURCE.parse_item(
        {**payload["jobs"][0], "locationRestrictions": ["Germany", "Kazakhstan"]}
    ).countries == ["DE", "KZ"]


def test_himalayas_unknown_country_not_narrowed():
    item = {**load("himalayas.json")["jobs"][0], "locationRestrictions": ["Germany", "Narnia"]}
    job = himalayas.SOURCE.parse_item(item)
    assert job.remote_scope == "unknown" and job.countries == []
    assert job.location_raw == "Germany, Narnia"


def test_himalayas_fetch():
    seen = []

    def h(req):
        seen.append(dict(req.url.params))
        page = int(req.url.params.get("page", 1))
        body = load("himalayas.json") if page == 1 else {"jobs": []}
        return httpx.Response(200, json=body)

    jobs = himalayas.SOURCE.fetch(client(h), set(), lambda j: True, {"max_pages": 3})
    assert len(jobs) == 20
    assert {p["q"] for p in seen} == set(himalayas.TERMS)
    assert all(p["worldwide"] == "true" for p in seen)
    assert len(seen) == 2 * len(himalayas.TERMS)


def test_himalayas_stops_at_known():
    first = load("himalayas.json")["jobs"][0]["guid"]
    seen = []

    def h(req):
        seen.append(1)
        return httpx.Response(200, json=load("himalayas.json"))

    himalayas.SOURCE.fetch(client(h), {first}, lambda j: True, {"max_pages": 5})
    assert len(seen) == len(himalayas.TERMS)


def test_remoteok_legal_skipped():
    payload = load("remoteok.json")
    assert "legal" in payload[0]
    items = remoteok.parse_payload(payload)
    assert len(items) == len(payload) - 1 and all("legal" not in i for i in items)
    job = first_job(remoteok, payload)
    assert "remoteok.com" in job.url.lower()
    assert job.url == job.raw["url"]
    paid = next(i for i in items if i["salary_min"])
    j = remoteok.SOURCE.parse_item(paid)
    assert j.salary_min == paid["salary_min"] and j.salary_currency == "USD"
    assert j.salary_period == "year"
    free = next(i for i in items if not i["salary_min"])
    assert remoteok.SOURCE.parse_item(free).salary_min is None


def test_remoteok_it_filter():
    items = remoteok.parse_payload(load("remoteok.json"))
    base = items[0]
    sales = {**base, "position": "Account Executive", "tags": ["sales", "customer support"]}
    assert remoteok.SOURCE.parse_item(sales) is None
    assert remoteok.SOURCE.parse_item({**sales, "tags": ["python"]}) is not None
    assert remoteok.SOURCE.parse_item({**sales, "position": "Senior Backend Engineer"}) is not None
    kept = [i for i in items if remoteok.SOURCE.parse_item(i)]
    assert 0 < len(kept) < len(items)


def test_remoteok_fetch():
    n = len([i for i in remoteok.parse_payload(load("remoteok.json"))
             if remoteok.SOURCE.parse_item(i)])
    jobs = remoteok.SOURCE.fetch(
        client(lambda r: httpx.Response(200, json=load("remoteok.json"))),
        set(), lambda j: True, {"max_pages": 5})
    assert len(jobs) == n


def test_jobicy_anywhere():
    payload = load("jobicy.json")
    item = next(i for i in jobicy.parse_payload(payload) if i["jobGeo"] == "Anywhere")
    job = jobicy.SOURCE.parse_item(item)
    assert job.remote_scope == "worldwide" and job.location_raw == "Anywhere"
    assert jobicy.parse_payload({"jobs": [], "success": True}) == []


def test_jobicy_fetch():
    seen = []

    def h(req):
        seen.append(dict(req.url.params))
        return httpx.Response(200, json=load("jobicy.json"))

    jobs = jobicy.SOURCE.fetch(client(h), set(), lambda j: True, {"max_pages": 5})
    assert [p["industry"] for p in seen] == list(jobicy.INDUSTRIES)
    assert all(p["count"] == "100" for p in seen)
    assert len(jobs) == 100  # same ids from every industry are de-duplicated


def test_workingnomads_non_it_dropped():
    items = workingnomads.parse_payload(load("workingnomads.json"))
    non_it = next(i for i in items if i["category_name"] == "Administration")
    assert workingnomads.SOURCE.parse_item(non_it) is None
    dev = next(i for i in items if i["category_name"] == "Development")
    assert workingnomads.SOURCE.parse_item(dev) is not None
    glob = workingnomads.SOURCE.parse_item({**dev, "location": "Global"})
    assert glob.remote_scope == "worldwide"
    assert workingnomads.SOURCE.parse_item({**dev, "location": "USA only"}).remote_scope == "restricted"


def test_workingnomads_fetch():
    jobs = workingnomads.SOURCE.fetch(
        client(lambda r: httpx.Response(200, json=load("workingnomads.json"))),
        set(), lambda j: True, {"max_pages": 5})
    assert 0 < len(jobs) < 35
