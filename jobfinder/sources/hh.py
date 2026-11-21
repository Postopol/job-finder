from __future__ import annotations

import html as _html
import json
import logging
import re

from selectolax.lexbor import LexborHTMLParser

from ..http import PoliteClient, SourceError
from ..models import Job
from . import register
from .base import ParseError, Source, describe_new, paged
from .geo import utc_from_iso

log = logging.getLogger(__name__)

API_URL = "https://api.hh.ru/vacancies"
API_DETAIL_URL = "https://api.hh.ru/vacancies/{id}"
SEARCH_URL = "https://hh.ru/search/vacancy"
VACANCY_URL = "https://hh.ru/vacancy/{id}"
# category «Информационные технологии» of https://api.hh.ru/professional_roles (fetched 2026-11-22)
IT_ROLES = ("10", "157", "12", "156", "150", "36", "125", "165", "34", "160", "104", "25", "116",
            "155", "112", "164", "73", "96", "107", "113", "114", "148", "121", "126", "124")
HH_USER_AGENT = "job-finder/1.0"  # hh API rejects browser UAs (bad_user_agent)
STATE_ID = "HH-Lux-InitialState"
STATE_PATH = ("vacancySearchResult", "vacancies")  # key path inside the embedded state (site pages)
DESCRIPTION_SELECTOR = '[data-qa="vacancy-description"]'
_TEMPLATE = re.compile(r'<template[^>]*\bid="' + STATE_ID + r'"[^>]*>(.*?)</template>', re.S)
_CURRENCIES = {"RUR": "RUB", "BYR": "BYN"}
_PERIODS = {"MONTH": "month", "YEAR": "year", "HOUR": "hour"}
_EXPERIENCE = {"noExperience": "junior", "between1And3": "middle", "between3And6": "senior",
               "moreThan6": "senior"}
_TITLE_LEVELS = (("lead", re.compile(r"\b(lead|team\s*lead|тимлид|руководитель)\b", re.I)),
                 ("senior", re.compile(r"\b(senior|sr|старший|ведущий)\b", re.I)),
                 ("junior", re.compile(r"\b(junior|jr|младший|стажёр|стажер|intern)\b", re.I)),
                 ("middle", re.compile(r"\b(middle|mid)\b", re.I)))
_HIGHLIGHT = re.compile(r"</?highlighttext>")


def parse_payload(payload) -> list[dict]:
    """Site search page (str) or API response (dict) -> list of vacancy dicts."""
    if isinstance(payload, dict):
        items = payload.get("items")
        if not isinstance(items, list):
            raise ParseError("нет списка items")
        return [i for i in items if isinstance(i, dict)]
    match = _TEMPLATE.search(payload) if isinstance(payload, str) else None
    if match is None:
        raise ParseError(f"нет тега {STATE_ID}")
    try:
        node = json.loads(_html.unescape(match.group(1)))
    except ValueError as e:
        raise ParseError(f"некорректный JSON в {STATE_ID}: {e}") from e
    for key in STATE_PATH:
        node = node.get(key) if isinstance(node, dict) else None
    if not isinstance(node, list):
        raise ParseError(f"нет списка {'.'.join(STATE_PATH)}")
    return [i for i in node if isinstance(i, dict)]


def _amount(v) -> int | None:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


def _seniority(title: str, experience) -> str | None:
    for level, pattern in _TITLE_LEVELS:
        if pattern.search(title):
            return level
    return _EXPERIENCE.get(str(experience))


def _api_remote(item: dict) -> bool:
    sched = item.get("schedule")
    if isinstance(sched, dict) and sched.get("id") == "remote":
        return True
    formats = item.get("work_format")
    return isinstance(formats, list) and any(isinstance(f, dict) and f.get("id") == "REMOTE" for f in formats)


def _page_remote(item: dict) -> bool:
    formats = item.get("workFormats")
    if not isinstance(formats, list):
        return item.get("@workSchedule") == "remote"
    return any("REMOTE" in (f.get("workFormatsElement") or []) for f in formats
               if isinstance(f, dict) and isinstance(f.get("workFormatsElement"), list))


def _name(node) -> str | None:
    value = node.get("name") if isinstance(node, dict) else None
    return str(value) if value else None


class Hh(Source):
    name = "hh"
    lang = "ru"
    full_listing = False
    method = "API или страница поиска"  # API with settings hh_token, otherwise the search page

    def parse_item(self, item: dict) -> Job | None:
        if "vacancyId" in item:
            return self._from_page(item)
        raw_id, title = item.get("id"), item.get("name")
        if raw_id is None or not title or not _api_remote(item):
            return None
        snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
        preview = " ".join(_HIGHLIGHT.sub("", str(snippet[k])) for k in ("requirement", "responsibility")
                           if snippet.get(k))
        sal = item.get("salary_range") if isinstance(item.get("salary_range"), dict) else item.get("salary")
        sal = sal if isinstance(sal, dict) else {}
        mode = sal.get("mode") if isinstance(sal.get("mode"), dict) else {}
        exp = item.get("experience") if isinstance(item.get("experience"), dict) else {}
        return self._job(
            str(raw_id), title, _name(item.get("employer")), sal.get("from"), sal.get("to"),
            sal.get("currency"), mode.get("id", "MONTH"), _name(item.get("area")),
            exp.get("id"), item.get("published_at"), item, preview)

    def _from_page(self, item: dict) -> Job | None:
        title = item.get("name")
        if not title or not _page_remote(item):
            return None
        comp = item.get("compensation") if isinstance(item.get("compensation"), dict) else {}
        pub = item.get("publicationTime")
        return self._job(
            str(item["vacancyId"]), title, item.get("company", {}).get("visibleName")
            if isinstance(item.get("company"), dict) else None,
            comp.get("from"), comp.get("to"), comp.get("currencyCode"), comp.get("mode", "MONTH"),
            _name(item.get("area")), item.get("workExperience"),
            pub.get("$") if isinstance(pub, dict) else None, item, "")

    def _job(self, source_id, title, company, lo, hi, currency, mode, area, experience,
             published, raw, preview) -> Job:
        lo, hi = _amount(lo), _amount(hi)
        has_salary = lo is not None or hi is not None
        currency = str(currency).upper() if currency else None
        return Job(
            source=self.name, source_id=source_id, url=VACANCY_URL.format(id=source_id), title=title,
            company=company, lang=self.lang,
            description_html=f"<p>{_html.escape(preview)}</p>" if preview else "", description_text=preview,
            salary_min=lo, salary_max=hi,
            salary_currency=_CURRENCIES.get(currency, currency) if has_salary else None,
            salary_period=_PERIODS.get(str(mode).upper()) if has_salary else None,
            location_raw=area, work_format="remote", remote_scope="unknown",
            seniority=_seniority(title, experience), published_at=utc_from_iso(published), raw=raw)

    def _describe_api(self, client: PoliteClient, job: Job, headers: dict) -> None:
        try:
            data = client.get(API_DETAIL_URL.format(id=job.source_id), headers=headers).json()
            text, skills = data.get("description"), data.get("key_skills")
        except SourceError as e:
            log.info("%s: описание %s не загружено: %s", self.name, job.source_id, e)
            return
        except (ValueError, AttributeError) as e:
            log.warning("%s: формат ответа вакансии %s изменился: %r", self.name, job.source_id, e)
            return
        if isinstance(text, str) and text.strip():
            job.description_html = text
            job.description_text = ""  # recomputed from the full HTML by normalize
        if isinstance(skills, list):
            job.stack = [str(s["name"]) for s in skills if isinstance(s, dict) and s.get("name")]

    def _describe_page(self, client: PoliteClient, job: Job) -> None:
        try:
            body = client.get(job.url).text
        except SourceError as e:
            log.info("%s: описание %s не загружено: %s", self.name, job.source_id, e)
            return
        node = LexborHTMLParser(body).css_first(DESCRIPTION_SELECTOR)
        if node is None:
            log.warning("%s: формат страницы вакансии %s изменился: нет %s", self.name, job.source_id,
                        DESCRIPTION_SELECTOR)
            return
        text = (node.inner_html or "").strip()
        if text:
            job.description_html = text
            job.description_text = ""

    def fetch(self, client: PoliteClient, known: set[str], wants, settings: dict) -> list[Job]:
        token = str(settings.get("hh_token") or "").strip()
        headers = {"Authorization": f"Bearer {token}", "HH-User-Agent": HH_USER_AGENT} if token else None
        seen: set[str] = set()

        def page(n: int) -> list[dict]:
            if token:
                params = {"schedule": "remote", "professional_role": list(IT_ROLES), "per_page": 100,
                          "page": n - 1, "order_by": "publication_time"}
                items = parse_payload(client.get(API_URL, params=params, headers=headers).json())
                key = "id"
            else:
                params = {"schedule": "remote", "professional_role": list(IT_ROLES),
                          "order_by": "publication_time", "items_on_page": 50, "page": n - 1}
                items = parse_payload(client.get(SEARCH_URL, params=params).text)
                key = "vacancyId"
            fresh = [i for i in items if str(i.get(key)) not in seen]  # the site repeats the last page
            seen.update(str(i.get(key)) for i in fresh)
            return fresh

        jobs = paged(page, self.parse_item, known, int(settings.get("max_pages", 5)))
        if token:
            def describe(job: Job) -> None:
                self._describe_api(client, job, headers)
        else:
            def describe(job: Job) -> None:
                self._describe_page(client, job)
        return describe_new(jobs, known, wants, describe, self.name)


SOURCE = register(Hh())
