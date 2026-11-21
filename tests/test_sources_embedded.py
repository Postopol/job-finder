import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from jobfinder.http import PoliteClient
from jobfinder.sources import REGISTRY, arc, hirify, rocketship
from jobfinder.sources.base import ParseError

FIX = Path(__file__).parent / "fixtures"


def html(name):
    return (FIX / name).read_text(encoding="utf-8")


def client(handler):
    return PoliteClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)


def page(body):
    return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"})


def first_job(mod, text):
    for item in mod.parse_payload(text):
        job = mod.SOURCE.parse_item(item)
        if job is not None:
            return job
    raise AssertionError("no job parsed")


CASES = [(arc, "arc.html", "en"), (rocketship, "rocketship.html", "en"), (hirify, "hirify.html", "ru")]


@pytest.mark.parametrize("mod,fixture,lang", CASES)
def test_common(mod, fixture, lang):
    text = html(fixture)
    assert len(mod.parse_payload(text)) >= 1
    job = first_job(mod, text)
    assert job.title and job.source_id and job.url.startswith("https://")
    assert job.source == mod.SOURCE.name and job.lang == lang
    assert job.raw is not None
    json.dumps(job.raw)
    assert job.published_at is not None and job.published_at.utcoffset() == timedelta(0)
    assert REGISTRY[mod.SOURCE.name] is mod.SOURCE
    assert mod.SOURCE.method == "JSON сайта"
    assert mod.SOURCE.full_listing is False


@pytest.mark.parametrize("mod,fixture,lang", CASES)
def test_parse_item_never_raises_on_odd_items(mod, fixture, lang):
    for odd in ({}, {"title": None}, {"id": 1}, {"requiredCountries": None, "title": "x"}):
        mod.SOURCE.parse_item(odd)


NEXT_NO_KEY = ('<html><script id="__NEXT_DATA__" type="application/json">'
               '{"props": {"pageProps": {"other": []}}}</script></html>')
NUXT_NO_KEY = ('<html><script id="__NUXT_DATA__" type="application/json">'
               '[{"data": 1}, {}]</script></html>')


@pytest.mark.parametrize("mod,no_key", [(arc, NEXT_NO_KEY), (rocketship, NEXT_NO_KEY),
                                        (hirify, NUXT_NO_KEY)])
def test_layout_change_raises(mod, no_key):
    for bad in ("<html><body>new design</body></html>", no_key):
        with pytest.raises(ParseError, match="формат страницы изменился"):
            mod.parse_payload(bad)


# --- arc ---

def test_arc_empty_required_countries_is_worldwide():
    items = arc.parse_payload(html("arc.html"))
    empty = next(i for i in items if not i["requiredCountries"])
    job = arc.SOURCE.parse_item(empty)
    assert job.remote_scope == "worldwide" and job.countries == []
    us = next(i for i in items if i["requiredCountries"] == ["US"])
    j = arc.SOURCE.parse_item(us)
    assert j.remote_scope == "countries" and j.countries == ["US"]


def test_arc_salary_timezone_url():
    items = arc.parse_payload(html("arc.html"))
    hourly = next(i for i in items if i["minHourlyRate"] and not i["minAnnualSalary"])
    j = arc.SOURCE.parse_item(hourly)
    assert (j.salary_min, j.salary_max) == (hourly["minHourlyRate"], hourly["maxHourlyRate"])
    assert j.salary_period == "hour" and j.salary_currency == "USD"
    annual = next(i for i in items if i["minAnnualSalary"])
    assert arc.SOURCE.parse_item(annual).salary_period == "year"
    tz = arc.SOURCE.parse_item({**hourly, "clientTimeZoneRestriction": "overlap", "timeZoneOffset": "+05:30"})
    assert tz.timezones == ["UTC+5.5"]
    none = arc.SOURCE.parse_item({**hourly, "clientTimeZoneRestriction": None, "timeZoneOffset": "+05:30"})
    assert none.timezones == []
    assert j.url == f"https://arc.dev/remote-jobs/details/{hourly['urlString']}-{hourly['randomKey']}"
    assert j.work_format == "remote" and j.stack


def test_arc_fetch_details_only_for_new_wanted():
    seen = []

    def h(req):
        seen.append(req.url.path)
        return page(html("arc_detail.html") if "/details/" in req.url.path else html("arc.html"))

    jobs = arc.SOURCE.fetch(client(h), set(), lambda j: True, {"max_pages": 5})
    assert len(jobs) == len(arc.parse_payload(html("arc.html")))
    assert seen[0] == "/remote-jobs" and len(seen) == 1 + len(jobs)
    assert all(j.description_html and "<script" not in j.description_html for j in jobs)

    seen.clear()
    known = {jobs[0].source_id}
    wanted = {jobs[1].source_id}
    arc.SOURCE.fetch(client(h), known, lambda j: j.source_id in wanted, {})
    assert len(seen) == 2  # list + one detail (known and unwanted skipped)


# --- rocketship ---

def test_rocketship_stack_seniority_scope():
    items = rocketship.parse_payload(html("rocketship.html"))
    item = items[0]
    job = rocketship.SOURCE.parse_item(item)
    assert job.stack == item["techStack"] and job.stack
    assert job.remote_scope == "worldwide" and job.seniority == "senior"
    assert job.url.startswith("https://www.remoterocketship.com/")
    jr = rocketship.SOURCE.parse_item({**item, "isSenior": False, "isMidLevel": False, "isJunior": True})
    assert jr.seniority == "junior"
    cs = rocketship.SOURCE.parse_item({**item, "location": "Germany", "locationCountries": ["Germany"]})
    assert cs.remote_scope == "countries" and cs.countries == ["DE"]
    paid = rocketship.SOURCE.parse_item({**item, "salaryRange": {
        "min": 20000, "max": 30000, "currencyCode": "USD", "salaryType": "per year"}})
    assert (paid.salary_min, paid.salary_max, paid.salary_period) == (20000, 30000, "year")


def test_rocketship_fetch():
    seen = []

    def h(req):
        seen.append(req.url.path)
        return page(html("rocketship.html"))

    jobs = rocketship.SOURCE.fetch(client(h), set(), lambda j: True, {"max_pages": 5})
    assert seen == [f"/country/worldwide/jobs/{r}" for r in rocketship.ROLES]
    assert len(jobs) == len(rocketship.parse_payload(html("rocketship.html")))  # same ids de-duplicated


# --- hirify ---

def test_hirify_mapping():
    items = hirify.parse_payload(html("hirify.html"))
    glob = next(i for i in items if i["remote_type"] == "global" and not i.get("suppress_distribution"))
    j = hirify.SOURCE.parse_item(glob)
    assert j.remote_scope == "worldwide" and j.work_format == "remote"
    assert j.stack == [t["name"] for t in glob["tags"]] and j.seniority
    assert j.url == f"https://hirify.me/jobs/{glob['slug']}" and j.source_id == str(glob["id"])
    assert j.raw["source"] == glob["source"]
    kz = next(i for i in items if "kazakhstan" in i["eligible_countries"])
    k = hirify.SOURCE.parse_item(kz)
    assert k.remote_scope == "countries" and "RU" in k.countries and "KZ" in k.countries
    ru = next(i for i in items if i["salary"])
    r = hirify.SOURCE.parse_item(ru)
    assert r.salary_currency == "RUB" and r.salary_min == ru["salary"]["min"]
    assert r.salary_period == "month"
    assert hirify.SOURCE.parse_item({**glob, "grades": [{"name": "middle"}, {"name": "senior"}]}).seniority == "senior"
    assert hirify.SOURCE.parse_item({**glob, "work_format": ["hybrid"]}).work_format == "hybrid"


def test_hirify_demo_vacancy_dropped():
    items = hirify.parse_payload(html("hirify.html"))
    demo = next(i for i in items if i.get("suppress_distribution"))
    assert hirify.SOURCE.parse_item(demo) is None


def test_hirify_fetch_specializations_no_page_param():
    seen = []

    def h(req):
        seen.append(dict(req.url.params))
        if req.url.path.startswith("/jobs/"):
            return page(html("hirify_detail.html"))
        return page(html("hirify.html"))

    jobs = hirify.SOURCE.fetch(client(h), set(), lambda j: False, {"max_pages": 5})
    lists = [p for p in seen if "specializations" in p]
    assert [p["specializations"] for p in lists] == list(hirify.SPECIALIZATIONS)
    assert all("page" not in p and p["work_format"] == "remote" and p["vacancy_language"] == "ru"
               and p["hide_global_vacancies"] == "1" for p in lists)
    assert len(seen) == len(lists) and jobs  # wants() False -> no detail requests


def test_hirify_detail_fills_description():
    seen = []

    def h(req):
        seen.append(req.url.path)
        if req.url.path.startswith("/jobs/"):
            return page(html("hirify_detail.html"))
        return page(html("hirify.html"))

    jobs = hirify.SOURCE.fetch(client(h), set(), lambda j: True, {})
    assert any(p.startswith("/jobs/") for p in seen)
    assert any("Django" in j.description_html and len(j.description_html) > 500 for j in jobs)


# --- detail failures are visible ---

BAD_DETAIL = '<html><script id="__NEXT_DATA__">{"props": {"pageProps": {}}}</script></html>'
BAD_NUXT = '<html><script id="__NUXT_DATA__">[{"data": 1}, {}]</script></html>'


@pytest.mark.parametrize("mod,listing,bad", [(arc, "arc.html", BAD_DETAIL), (hirify, "hirify.html", BAD_NUXT)])
def test_detail_layout_change_warns_and_keeps_job(mod, listing, bad, caplog):
    def h(req):
        return page(html(listing) if mod is hirify and "/jobs/" not in req.url.path
                    or mod is arc and "/details/" not in req.url.path else bad)

    with caplog.at_level("INFO", logger=mod.__name__):
        jobs = mod.SOURCE.fetch(client(h), set(), lambda j: True, {})
    assert jobs
    assert any(r.levelname == "WARNING" and mod.SOURCE.name in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("mod,listing", [(arc, "arc.html"), (hirify, "hirify.html")])
def test_detail_http_error_keeps_job_without_warning(mod, listing, caplog):
    def h(req):
        if "/details/" in req.url.path or "/jobs/" in req.url.path:
            return httpx.Response(404)
        return page(html(listing))

    with caplog.at_level("INFO", logger=mod.__name__):
        jobs = mod.SOURCE.fetch(client(h), set(), lambda j: True, {})
    assert jobs
    assert not [r for r in caplog.records if r.levelname == "WARNING"]
    assert any(r.levelname == "INFO" for r in caplog.records)
