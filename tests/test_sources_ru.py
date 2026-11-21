import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from jobfinder.http import PoliteClient, SourceBlocked
from jobfinder.sources import REGISTRY, getmatch, habr, hh
from jobfinder.sources.base import ParseError

FIX = Path(__file__).parent / "fixtures"


def text(name):
    return (FIX / name).read_text(encoding="utf-8")


def client(handler):
    return PoliteClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)


def page(body):
    return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"})


def js(body):
    return httpx.Response(200, json=body)


def payload(mod):
    if mod is hh:
        return text("hh_search.html")
    return json.loads(text("habr.json" if mod is habr else "getmatch.json"))


def first_job(mod):
    for item in mod.parse_payload(payload(mod)):
        job = mod.SOURCE.parse_item(item)
        if job is not None:
            return job
    raise AssertionError("no job parsed")


METHODS = {hh: "API или страница поиска", habr: "JSON сайта", getmatch: "JSON сайта"}


@pytest.mark.parametrize("mod", [hh, habr, getmatch])
def test_common(mod):
    assert len(mod.parse_payload(payload(mod))) >= 1
    job = first_job(mod)
    assert job.title and job.source_id and job.url.startswith("https://")
    assert job.source == mod.SOURCE.name and job.lang == "ru"
    assert job.raw is not None
    json.dumps(job.raw)
    assert job.published_at is not None and job.published_at.utcoffset() == timedelta(0)
    assert REGISTRY[mod.SOURCE.name] is mod.SOURCE
    assert mod.SOURCE.method == METHODS[mod]
    assert mod.SOURCE.full_listing is False


@pytest.mark.parametrize("mod", [hh, habr, getmatch])
def test_parse_item_never_raises_on_odd_items(mod):
    for odd in ({}, {"title": None}, {"id": 1}, {"salary": "x", "company": 5, "skills": 3, "title": "x"},
                {"vacancyId": 1, "name": "x", "compensation": 3, "area": "y", "company": []},
                {"id": 1, "position": "x", "url": "/v/1", "location_requirements": "z", "skills_objects": 4}):
        mod.SOURCE.parse_item(odd)


def test_layout_change_raises():
    for bad in ('<html><template id="HH-Lux-InitialState">{&#34;a&#34;: 1}</template></html>',
                "<html>captcha</html>", {"items": "x"}, {}):
        with pytest.raises(ParseError, match="формат страницы изменился"):
            hh.parse_payload(bad)
    for mod in (habr, getmatch):
        for bad in ({"oops": 1}, [], {"list": "x", "offers": "x"}):
            with pytest.raises(ParseError, match="формат страницы изменился"):
                mod.parse_payload(bad)


# --- hh ---

def test_hh_roles_constant():
    roles = json.loads(text("hh_roles.json"))
    it = next(c for c in roles["categories"] if c["name"] == "Информационные технологии")
    assert list(hh.IT_ROLES) == [r["id"] for r in it["roles"]] and "96" in hh.IT_ROLES


def test_hh_page_mapping():
    items = hh.parse_payload(text("hh_search.html"))
    by_id = {i["vacancyId"]: hh.SOURCE.parse_item(i) for i in items}
    paid = by_id[139503360]
    assert paid.title == "Fullstack-разработчик" and paid.url == "https://hh.ru/vacancy/139503360"
    assert (paid.salary_min, paid.salary_max) == (None, 300000)
    assert paid.salary_currency == "RUB" and paid.salary_period == "month"
    assert paid.work_format == "remote" and paid.location_raw == "Москва" and paid.lang == "ru"
    assert paid.company and paid.seniority in {None, "middle", "senior", "junior", "lead"}
    assert by_id[138815023].salary_min is None and by_id[138815023].salary_currency is None
    assert paid.published_at.utcoffset() == timedelta(0)


API_ITEM = {
    "id": "123", "name": "Python developer", "alternate_url": "https://hh.ru/vacancy/123",
    "area": {"name": "Алматы"}, "employer": {"name": "Acme"},
    "salary": {"from": 1000, "to": None, "currency": "USD", "gross": True},
    "published_at": "2026-11-21T23:41:30+0300", "experience": {"id": "between3And6"},
    "schedule": {"id": "remote"}, "snippet": {"requirement": "Знание <highlighttext>Python</highlighttext>"},
}


def test_hh_api_mapping():
    job = hh.SOURCE.parse_item(API_ITEM)
    assert job.source_id == "123" and job.url == "https://hh.ru/vacancy/123"
    assert job.company == "Acme" and job.location_raw == "Алматы" and job.work_format == "remote"
    assert (job.salary_min, job.salary_max, job.salary_currency) == (1000, None, "USD")
    assert job.seniority == "senior" and job.published_at.hour == 20
    rur = hh.SOURCE.parse_item({**API_ITEM, "salary": {"from": 5, "to": 6, "currency": "RUR"}})
    assert rur.salary_currency == "RUB"


def test_hh_fetch_with_token_builds_api_urls():
    seen = []
    reqs = []

    def h(req):
        reqs.append(req)
        seen.append((req.url.host, req.url.path, req.url.params.multi_items(), req.headers.get("authorization")))
        if req.url.path == "/vacancies":
            items = [API_ITEM, {**API_ITEM, "id": "124", "alternate_url": "https://hh.ru/vacancy/124"}]
            return js({"items": items if req.url.params["page"] == "0" else [], "pages": 1})
        return js({"id": req.url.path.rsplit("/", 1)[1], "description": "<p>Полное описание</p>",
                   "key_skills": [{"name": "Python"}, {"name": "SQL"}]})

    jobs = hh.SOURCE.fetch(client(h), {"124"}, lambda j: j.source_id == "123",
                           {"hh_token": "TOK", "max_pages": 3})
    assert all(s[0] == "api.hh.ru" and s[3] == "Bearer TOK" for s in seen)
    assert all(r.headers.get("hh-user-agent") == "job-finder/1.0" for r in reqs)
    host, path, params, _ = seen[0]
    p = dict(params)
    assert path == "/vacancies" and p["schedule"] == "remote" and p["per_page"] == "100"
    assert p["page"] == "0" and p["order_by"] == "publication_time"
    assert [v for k, v in params if k == "professional_role"] == list(hh.IT_ROLES)
    details = [s for s in seen if s[1].startswith("/vacancies/")]
    assert [d[1] for d in details] == ["/vacancies/123"]  # 124 is known -> no detail
    j123 = next(j for j in jobs if j.source_id == "123")
    assert "Полное описание" in j123.description_html and j123.stack == ["Python", "SQL"]
    assert len(seen) == 2  # known job stops paging; one list + one detail


def test_hh_fetch_without_token_uses_search_page():
    seen = []

    def h(req):
        seen.append((req.url.host, req.url.path, req.url.params.multi_items(), req.headers.get("authorization")))
        if req.url.path == "/search/vacancy":
            return page(text("hh_search.html"))
        return page(text("hh_detail.html"))

    jobs = hh.SOURCE.fetch(client(h), set(), lambda j: j.source_id == "139503360", {"max_pages": 1})
    assert seen[0][0] == "hh.ru" and seen[0][3] is None
    p = dict(seen[0][2])
    assert p["schedule"] == "remote" and p["items_on_page"] == "50" and p["page"] == "0"
    assert p["order_by"] == "publication_time"
    assert [v for k, v in seen[0][2] if k == "professional_role"] == list(hh.IT_ROLES)
    assert [s[1] for s in seen[1:]] == ["/vacancy/139503360"]
    job = next(j for j in jobs if j.source_id == "139503360")
    assert "NestJS" in job.description_html
    assert len(jobs) == len(hh.parse_payload(text("hh_search.html")))


def test_hh_blank_token_means_no_token():
    seen = []

    def h(req):
        seen.append(req.url.host)
        return page(text("hh_search.html"))

    hh.SOURCE.fetch(client(h), set(), lambda j: False, {"hh_token": "  ", "max_pages": 1})
    assert seen == ["hh.ru"]


def test_hh_pages_until_repeat_or_empty():
    calls = []

    def h(req):
        calls.append(req.url.params["page"])
        return page(text("hh_search.html"))  # the site repeats the last page past the end

    hh.SOURCE.fetch(client(h), set(), lambda j: False, {"max_pages": 5})
    assert calls == ["0", "1"]


@pytest.mark.parametrize("withtoken", [True, False])
def test_hh_detail_failure_and_block_keep_jobs(withtoken, caplog):
    settings = {"hh_token": "T"} if withtoken else {}

    def listing(req):
        if req.url.path in ("/vacancies", "/search/vacancy"):
            return js({"items": [API_ITEM]}) if withtoken else page(text("hh_search.html"))
        return None

    def h404(req):
        return listing(req) or httpx.Response(404)

    with caplog.at_level("INFO", logger=hh.__name__):
        jobs = hh.SOURCE.fetch(client(h404), set(), lambda j: True, {**settings, "max_pages": 1})
    assert jobs and not [r for r in caplog.records if r.levelname == "WARNING"]

    def h429(req):
        return listing(req) or httpx.Response(429)

    c = client(h429)
    blocked = hh.SOURCE.fetch(c, set(), lambda j: True, {**settings, "max_pages": 1})
    assert c.blocked == 429
    assert [j.source_id for j in blocked] == [j.source_id for j in jobs]


def test_hh_detail_layout_change_warns(caplog):
    def h(req):
        return page(text("hh_search.html")) if req.url.path == "/search/vacancy" else page("<html>нет</html>")

    with caplog.at_level("INFO", logger=hh.__name__):
        jobs = hh.SOURCE.fetch(client(h), set(), lambda j: True, {"max_pages": 1})
    assert jobs and any(r.levelname == "WARNING" and "hh" in r.getMessage() for r in caplog.records)


# --- habr ---

def test_habr_mapping():
    items = habr.parse_payload(payload(habr))
    by_id = {i["id"]: habr.SOURCE.parse_item(i) for i in items}
    job = by_id[1000169259]
    assert job.url == "https://career.habr.com/vacancies/1000169259"
    assert (job.salary_min, job.salary_max, job.salary_currency, job.salary_period) == (240000, 250000, "RUB", "month")
    assert job.stack[:3] == ["Python", "SQL", "ETL"] and job.seniority == "senior"
    assert job.company == "Top Selection" and job.work_format == "remote"
    msk = next(j for j in by_id.values() if j.location_raw == "Москва")
    assert msk.salary_min is None and msk.salary_currency is None
    assert habr.SOURCE.parse_item({**items[0], "qualification": "Junior"}).seniority == "junior"


def test_habr_fetch_params_and_detail():
    seen = []

    def h(req):
        seen.append((req.url.path, dict(req.url.params)))
        if req.url.path == "/api/frontend/vacancies":
            return js(payload(habr) if req.url.params["page"] == "1" else {"list": [], "meta": {}})
        return page(text("habr_detail.html"))

    jobs = habr.SOURCE.fetch(client(h), set(), lambda j: j.source_id == "1000169259", {"max_pages": 3})
    path, p = seen[0]
    assert p == {"remote": "true", "type": "all", "sort": "date", "per_page": "50", "page": "1"}
    assert [s[0] for s in seen[1:2]] == ["/api/frontend/vacancies"]  # second (empty) list page
    assert [s[0] for s in seen[2:]] == ["/vacancies/1000169259"]
    job = next(j for j in jobs if j.source_id == "1000169259")
    assert "Top Selection" in job.description_html and "<script" not in job.description_html
    items = habr.parse_payload(payload(habr))
    assert len(jobs) == sum(habr.SOURCE.parse_item(i) is not None for i in items) == len(items) - 2


def test_habr_non_it_divisions_dropped():
    by_title = {i["title"]: i for i in habr.parse_payload(payload(habr))}
    bd = by_title["Менеджер по развитию бизнеса (Сибирь)"]  # division «Менеджер по продажам»
    assert habr.SOURCE.parse_item(bd) is None
    assert habr.SOURCE.parse_item(by_title["Ресерчер"]) is None  # HR division
    assert habr.SOURCE.parse_item(by_title["Middle Golang Разработчик"]) is not None
    marketing = {**by_title["Middle Golang Разработчик"],
                 "divisions": [{"title": "Маркетолог", "href": "/vacancies/spec/marketing/marketer"}]}
    assert habr.SOURCE.parse_item(marketing) is None
    mixed = {**marketing, "divisions": [*marketing["divisions"], *by_title["Middle Golang Разработчик"]["divisions"]]}
    assert habr.SOURCE.parse_item(mixed) is not None  # one IT division is enough
    assert habr.SOURCE.parse_item({**bd, "divisions": None}) is not None


def test_habr_known_job_stops_paging_and_skips_detail():
    seen = []

    def h(req):
        seen.append(req.url.path)
        return js(payload(habr))

    habr.SOURCE.fetch(client(h), {"1000169259"}, lambda j: True, {"max_pages": 5})
    assert [s for s in seen if s.startswith("/vacancies/")] != ["/vacancies/1000169259"]
    assert seen.count("/api/frontend/vacancies") == 1


# --- getmatch ---

def test_getmatch_non_remote_is_none():
    items = getmatch.parse_payload(payload(getmatch))
    results = [(i, getmatch.SOURCE.parse_item(i)) for i in items]
    non = [i for i, j in results if not any(r.get("format") == "remote" for r in i["location_requirements"])]
    assert non and all(getmatch.SOURCE.parse_item(i) is None for i in non)
    assert any(j is not None for _, j in results)


def test_getmatch_mapping():
    by_id = {i["id"]: i for i in getmatch.parse_payload(payload(getmatch))}
    world = getmatch.SOURCE.parse_item(by_id[37324])
    assert world.url == "https://getmatch.ru/vacancies/37324-c-engineer"
    assert (world.salary_min, world.salary_max, world.salary_currency, world.salary_period) == (5000, 7000, "USD", "month")
    assert world.remote_scope == "worldwide" and world.countries == []
    assert world.stack[:3] == ["C++", "Python", "Linux"] and world.company == "Wunder Fund"
    assert world.work_format == "remote" and world.description_html
    ru = next(getmatch.SOURCE.parse_item(i) for i in by_id.values() if i["salary_currency"] == "RUB"
              and any(r["country"] == "Россия" for r in i["location_requirements"]))
    assert ru.remote_scope == "countries" and ru.countries == ["RU"] and ru.salary_currency == "RUB"
    nosal = getmatch.SOURCE.parse_item(next(
        i for i in by_id.values() if i["salary_hidden"]
        and any(r["format"] == "remote" for r in i["location_requirements"])))
    assert nosal.salary_min is None and nosal.salary_currency is None


def test_getmatch_inactive_dropped():
    item = next(i for i in getmatch.parse_payload(payload(getmatch)) if getmatch.SOURCE.parse_item(i))
    assert getmatch.SOURCE.parse_item({**item, "is_active": False}) is None


def test_getmatch_fetch_params_and_paging():
    seen = []

    def h(req):
        seen.append(dict(req.url.params))
        return js(payload(getmatch) if req.url.params["offset"] == "0" else {"offers": [], "meta": {}})

    jobs = getmatch.SOURCE.fetch(client(h), set(), lambda j: True, {"max_pages": 5})
    assert seen[0] == {"pa": "all", "limit": "100", "offset": "0"}
    assert seen[1]["offset"] == "100" and len(seen) == 2
    assert jobs and all(j.work_format == "remote" for j in jobs)


# --- per-item remote cut ---

def test_hh_page_non_remote_dropped():
    item = hh.parse_payload(text("hh_search.html"))[0]
    assert hh.SOURCE.parse_item(item) is not None
    office = {**item, "workFormats": [{"workFormatsElement": ["ON_SITE"]}]}
    assert hh.SOURCE.parse_item(office) is None
    hybrid = {**item, "workFormats": [{"workFormatsElement": ["REMOTE", "HYBRID"]}]}
    assert hh.SOURCE.parse_item(hybrid) is not None


def test_hh_page_hourly_salary_uses_per_mode_amounts():
    item = hh.parse_payload(text("hh_search.html"))[0]
    # live case: hh puts a monthly estimate in from/to and the hourly rate in perModeFrom
    hourly = {**item, "compensation": {"from": 514285, "currencyCode": "RUR", "gross": True,
                                       "perModeFrom": 5000, "mode": "HOUR"}}
    job = hh.SOURCE.parse_item(hourly)
    assert (job.salary_min, job.salary_max, job.salary_currency, job.salary_period) == \
        (5000, None, "RUB", "hour")
    # no per-mode amounts: from/to are already monthly
    monthly = {**item, "compensation": {"from": 514285, "currencyCode": "RUR", "mode": "HOUR"}}
    job = hh.SOURCE.parse_item(monthly)
    assert (job.salary_min, job.salary_period) == (514285, "month")
    # per-mode keys present but empty: fall back to from/to, keep the salary
    empty = {**item, "compensation": {"from": 300000, "to": 400000, "currencyCode": "RUR",
                                      "perModeFrom": None, "perModeTo": None, "mode": "MONTH"}}
    job = hh.SOURCE.parse_item(empty)
    assert (job.salary_min, job.salary_max, job.salary_period) == (300000, 400000, "month")


def test_hh_api_non_remote_dropped():
    assert hh.SOURCE.parse_item(API_ITEM) is not None
    assert hh.SOURCE.parse_item({**API_ITEM, "schedule": {"id": "fullDay"}}) is None
    assert hh.SOURCE.parse_item({**API_ITEM, "schedule": {"id": "fullDay"},
                                 "work_format": [{"id": "REMOTE"}]}) is not None


def test_habr_non_remote_dropped():
    item = habr.parse_payload(payload(habr))[0]
    assert habr.SOURCE.parse_item(item) is not None
    assert habr.SOURCE.parse_item({**item, "remoteWork": False}) is None
    assert habr.SOURCE.parse_item({k: v for k, v in item.items() if k != "remoteWork"}) is None


def test_getmatch_russia_only_offers_hidden():
    from jobfinder.collector import _prepare
    from jobfinder.filters import FilterConfig
    jobs = [j for j in map(getmatch.SOURCE.parse_item, getmatch.parse_payload(payload(getmatch))) if j]
    ru_only = [j for j in jobs if j.countries == ["RU"]]
    assert ru_only
    for j in ru_only:
        assert _prepare(j, FilterConfig(country="KZ")) == "restricted" and j.remote_scope == "countries"
