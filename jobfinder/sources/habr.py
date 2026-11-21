from __future__ import annotations

import logging

from selectolax.lexbor import LexborHTMLParser

from ..http import PoliteClient, SourceError
from ..models import Job
from . import register
from .base import ParseError, Source, describe_new, paged
from .geo import utc_from_iso

log = logging.getLogger(__name__)

SITE = "https://career.habr.com"
URL = SITE + "/api/frontend/vacancies"
LIST_KEY = "list"
DESCRIPTION_SELECTOR = ".vacancy-description__text"
_CURRENCIES = {"rur": "RUB", "rub": "RUB", "usd": "USD", "eur": "EUR", "kzt": "KZT", "byn": "BYN"}
_LEVELS = {"intern": "junior", "junior": "junior", "middle": "middle", "senior": "senior", "lead": "lead"}


# Habr Career is not IT-only. Specialization groups (the path of a division's href,
# /vacancies/spec/<group>/<spec>) and division titles that are not IT work.
NON_IT_GROUPS = {"sales", "marketing", "hr", "office", "accounting", "finance", "finances"}
NON_IT_DIVISIONS = {"менеджер по продажам", "маркетолог", "специалист по подбору персонала",
                    "рекрутер", "бухгалтер", "офис-менеджер", "менеджер по работе с клиентами"}


def _division_non_it(d: dict) -> bool:
    parts = str(d.get("href") or "").strip("/").split("/")
    group = parts[2] if len(parts) >= 4 and parts[:2] == ["vacancies", "spec"] else ""
    return group in NON_IT_GROUPS or str(d.get("title") or "").strip().lower() in NON_IT_DIVISIONS


def is_non_it(item: dict) -> bool:
    """True when every division of the vacancy is a non-IT one (sales, marketing, HR, ...)."""
    divisions = [d for d in item.get("divisions") or [] if isinstance(d, dict)] \
        if isinstance(item.get("divisions"), list) else []
    return bool(divisions) and all(_division_non_it(d) for d in divisions)


def parse_payload(payload) -> list[dict]:
    node = payload.get(LIST_KEY) if isinstance(payload, dict) else None
    if not isinstance(node, list):
        raise ParseError(f"нет списка {LIST_KEY}")
    return [j for j in node if isinstance(j, dict)]


def _amount(v) -> int | None:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


class Habr(Source):
    name = "habr"
    lang = "ru"
    full_listing = False
    detail_pages = True
    method = "JSON сайта"

    def parse_item(self, item: dict) -> Job | None:
        href, title = item.get("href"), item.get("title")
        if not href or not title or item.get("id") is None or item.get("archived") \
                or item.get("remoteWork") is not True or is_non_it(item):
            return None
        sal = item.get("salary") if isinstance(item.get("salary"), dict) else {}
        lo, hi = _amount(sal.get("from")), _amount(sal.get("to"))
        has_salary = lo is not None or hi is not None
        currency = str(sal.get("currency") or "").lower()
        company = item.get("company")
        places = [str(p["title"]) for p in item.get("locations") or [] if isinstance(p, dict) and p.get("title")] \
            if isinstance(item.get("locations"), list) else []
        skills = item.get("skills")
        return Job(
            source=self.name, source_id=str(item["id"]), url=SITE + str(href), title=title,
            company=company.get("title") if isinstance(company, dict) else None, lang=self.lang,
            salary_min=lo, salary_max=hi,
            salary_currency=(_CURRENCIES.get(currency) or currency.upper() or None) if has_salary else None,
            salary_period="month" if has_salary else None,
            location_raw=", ".join(places) or None, work_format="remote", remote_scope="unknown",
            seniority=_LEVELS.get(str(item.get("qualification")).lower()),
            stack=[str(s["title"]) for s in skills if isinstance(s, dict) and s.get("title")]
            if isinstance(skills, list) else [],
            published_at=utc_from_iso((item.get("publishedDate") or {}).get("date")
                                      if isinstance(item.get("publishedDate"), dict) else None),
            raw=item)

    def _describe(self, client: PoliteClient, job: Job) -> None:
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
            job.description_text = ""  # recomputed from the full HTML by normalize

    def fetch(self, client: PoliteClient, known: set[str], wants, settings: dict) -> list[Job]:
        def page(n: int) -> list[dict]:
            params = {"remote": "true", "type": "all", "sort": "date", "per_page": 50, "page": n}
            return parse_payload(client.get(URL, params=params).json())

        jobs = paged(page, self.parse_item, known, int(settings.get("max_pages", 5)))
        return describe_new(jobs, known, wants, lambda job: self._describe(client, job), self.name)


SOURCE = register(Habr())
