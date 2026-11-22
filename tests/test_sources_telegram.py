import json
import re
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from jobfinder.filters import FilterConfig, classify_scope, hidden_reason
from jobfinder.http import PoliteClient, SourceBlocked, SourceError
from jobfinder.normalize import normalize_job
from jobfinder.sources import REGISTRY, telegram
from jobfinder.sources.base import ParseError

FIX = Path(__file__).parent / "fixtures"
PAGE = (FIX / "telegram.html").read_text(encoding="utf-8")
SRC = telegram.SOURCE


def client(handler):
    return PoliteClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)


def items():
    return telegram.parse_payload(PAGE)


def job(msg_id):
    item = next(i for i in items() if i["id"] == msg_id)
    return SRC.parse_item(item)


def hidden(j):
    normalize_job(j)
    cfg = FilterConfig()
    j.remote_scope, j.countries = classify_scope(j, cfg.country)
    return hidden_reason(j, cfg)


# ---- page parsing

def test_parse_payload_reads_text_posts():
    got = items()
    assert [i["id"] for i in got] == [*range(101, 111), *range(112, 118)]  # 111 is photo-only
    first = got[0]
    assert first["channel"] == "testjobs"
    assert first["published_at"].startswith("2026-11-10T09:00:00")
    json.dumps(first)


def test_reply_quote_is_not_the_post_text():
    item = next(i for i in items() if i["id"] == 110)
    assert "Цитата" not in item["html"] and "Senior Frontend Developer" in item["html"]


def test_unavailable_channel_page_raises():
    page = "<html><head><title>Telegram: Contact @nope</title></head><body></body></html>"
    with pytest.raises(ParseError):
        telegram.parse_payload(page)


def test_registered():
    assert REGISTRY["telegram"] is SRC
    assert SRC.lang == "ru" and SRC.full_listing is False and SRC.method == "Каналы Telegram"


# ---- posts

def test_template_post():
    j = job(101)
    assert j.title == "QA Automation Engineer (Python)"
    assert j.company == "Тестовая Софт"
    assert j.salary_raw == "170 000–210 000 ₽ в месяц"
    assert j.work_format == "remote"
    assert j.source_id == "testjobs/101" and j.url == "https://t.me/testjobs/101"
    assert j.lang == "ru" and j.published_at.utcoffset() == timedelta(0)
    assert hidden(j) is None
    assert j.salary_min == 170000 and j.salary_currency == "RUB"
    assert "Python" in j.stack


def test_remote_only_in_russia_is_hidden():
    j = job(102)
    assert j.work_format == "remote" and j.countries == ["RU"]
    assert j.salary_raw is None  # «не указана»
    assert hidden(j) == "restricted"


def test_resume_digest_and_meetup_are_skipped():
    assert job(103) is None  # #резюме
    assert job(106) is None  # meetup announcement
    assert job(107) is None  # «Дайджест резюме»


def test_field_title_and_hybrid():
    j = job(104)
    assert j.title == "Senior DevOps Engineer"
    assert j.company == "БайерТех"
    assert j.work_format == "hybrid"
    assert j.salary_raw.startswith("от 300 000 до 350 000")
    assert hidden(j) == "hybrid"


def test_title_slash_company_and_remote_second_line():
    j = job(105)
    assert j.title == "Backend Engineer (Python / Django)"
    assert j.company == "Karta.io"
    assert j.work_format == "remote"


def test_relocation_without_remote_is_office():
    j = job(108)
    assert j.title == "Senior Backend Developer (Python)" and j.company == "Instories"
    assert j.work_format == "office"
    assert hidden(j) == "office"


def test_emoji_bullets_and_hashtag_format():
    j = job(109)
    assert j.title == "Senior Quant/ML Researcher (Crypto)"
    assert j.company == "Квант Фонд"
    assert j.work_format == "hybrid"
    assert j.salary_raw.startswith("6 500–8 000 USD")


def test_worldwide_remote_with_fields_below():
    j = job(110)
    assert j.title == "Senior Frontend Developer (React)"
    assert j.company == "Флоу Лабс" and j.salary_raw == "$4 000–5 500"
    assert j.work_format == "remote"
    assert hidden(j) is None and j.remote_scope == "worldwide"


def test_digest_skipped():
    assert job(112) is None


def test_company_with_ai_domain_dot_thousands_and_region():
    j = job(113)
    assert j.title == "Frontend Developer (Angular)" and j.company == "Healz.ai"
    assert j.salary_raw == "$5 000- $6 000"
    assert j.work_format == "remote" and "Europe" in j.location_raw
    assert hidden(j) == "restricted"  # Europe-only remote is not open to Kazakhstan
    assert j.salary_min == 5000 and j.salary_max == 6000


def test_link_text_dropped_from_title():
    assert job(114).title == "Senior Python Backend разработчик"


def test_title_after_preface_line():
    j = job(115)
    assert j.title == "AI Tools Backend Developer" and j.company == "Сайлент Рум"


def test_announcement_with_role_word_skipped():
    assert job(116) is None


def test_sentence_company_dropped_and_citizenship_field():
    j = job(117)
    assert j.title == "Senior Data Scientist"
    assert j.company is None
    assert j.countries == ["RU"] and hidden(j) == "restricted"
    assert j.salary_raw == "200 000-280 000 Рублей на руки"


def test_odd_items_return_none():
    for item in ({}, {"channel": "x", "id": None, "html": None},
                 {"channel": "x", "id": 1, "html": 5}, {"channel": "x", "id": 1, "html": ""}):
        assert SRC.parse_item(item) is None


# ---- channel names

@pytest.mark.parametrize("raw,name", [
    ("opento_dev", "opento_dev"), ("@opento_dev", "opento_dev"),
    ("https://t.me/opento_dev", "opento_dev"), ("t.me/s/jobforqa", "jobforqa"),
    ("https://t.me/jobforqa/1627", "jobforqa"), (" JobForQA ", "jobforqa"),
    ("no", None), ("плохое имя", None), ("https://example.com/x", None), ("", None),
])
def test_channel_name(raw, name):
    assert telegram.channel_name(raw) == name


# ---- fetch

def shifted(delta):
    """The fixture page with every post id lowered by `delta`."""
    return re.sub(r"testjobs/(\d+)", lambda m: f"testjobs/{int(m.group(1)) - delta}", PAGE)


def test_fetch_pages_back_until_known():
    calls = []

    def handler(req):
        calls.append(str(req.url))
        if req.url.params.get("before") == "101":
            return httpx.Response(200, text=shifted(100))
        return httpx.Response(200, text=PAGE)

    jobs = SRC.fetch(client(handler), set(), lambda j: True,
                     {"tg_channels": ["testjobs"], "max_pages": 2})
    assert calls == ["https://t.me/s/testjobs", "https://t.me/s/testjobs?before=101"]
    assert {j.source_id for j in jobs} >= {"testjobs/101", "testjobs/1"}

    calls.clear()  # a known post on the first page: no paging back
    SRC.fetch(client(handler), {"testjobs/104"}, lambda j: True,
              {"tg_channels": ["testjobs"], "max_pages": 5})
    assert calls == ["https://t.me/s/testjobs"]


def test_fetch_pages_capped():
    calls = []

    def handler(req):
        calls.append(str(req.url))
        before = int(req.url.params.get("before") or 111)
        return httpx.Response(200, text=shifted(111 - before))

    SRC.fetch(client(handler), set(), lambda j: True, {"tg_channels": ["testjobs"], "max_pages": 50})
    assert len(calls) == telegram.MAX_PAGES


def test_fetch_skips_missing_channel_and_keeps_others():
    def handler(req):
        if "nope" in str(req.url):
            return httpx.Response(200, text="<html><title>Telegram: Contact @nope</title></html>")
        return httpx.Response(200, text=PAGE)

    jobs = SRC.fetch(client(handler), set(), lambda j: True,
                     {"tg_channels": ["nope", "testjobs"], "max_pages": 1})
    assert any(j.source_id == "testjobs/101" for j in jobs)


def test_fetch_fails_when_no_channel_opens():
    def handler(req):
        return httpx.Response(404)

    with pytest.raises(SourceError):
        SRC.fetch(client(handler), set(), lambda j: True,
                  {"tg_channels": ["nope1", "nope2"], "max_pages": 1})


def test_fetch_rate_limit_keeps_what_was_collected():
    def handler(req):
        if "second" in str(req.url):
            return httpx.Response(429)
        return httpx.Response(200, text=PAGE)

    c = client(handler)
    jobs = SRC.fetch(c, set(), lambda j: True,
                     {"tg_channels": ["testjobs", "second", "third"], "max_pages": 1})
    assert jobs and c.blocked == 429

    with pytest.raises(SourceBlocked):  # blocked before anything was collected
        SRC.fetch(client(lambda r: httpx.Response(429)), set(), lambda j: True,
                  {"tg_channels": ["testjobs"], "max_pages": 1})


def test_fetch_with_no_channels_returns_nothing():
    def handler(req):
        raise AssertionError("no request expected")

    assert SRC.fetch(client(handler), set(), lambda j: True, {"tg_channels": []}) == []


def test_reparse_from_raw():
    j = job(101)
    again = SRC.parse_item(json.loads(json.dumps(j.raw)))
    assert again.title == j.title and again.source_id == j.source_id
