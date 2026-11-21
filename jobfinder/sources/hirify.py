from __future__ import annotations

import html as _html
import logging

from ..http import PoliteClient, SourceError
from ..models import Job
from . import register
from .base import ParseError, Source, nuxt_data, paged
from .geo import countries_from, utc_from_iso

log = logging.getLogger(__name__)
URL = "https://hirify.me/"
JOB_URL = "https://hirify.me/jobs/{slug}"
# IT specializations (codes verified against the site's own filter; `page` is disallowed by robots.txt)
SPECIALIZATIONS = ("backend_dev", "frontend_dev", "fullstack_dev", "devops",
                   "mobile_development", "ai_engineering")
LIST_PATH = ("data", "feed-fetch-service", "data")
_GRADES = {"intern": 1, "junior": 1, "middle": 2, "senior": 3, "lead": 4, "principal": 4}
_LEVELS = {1: "junior", 2: "middle", 3: "senior", 4: "lead"}
_PERIODS = {"month": "month", "year": "year", "hour": "hour"}


def parse_payload(page_html: str) -> list[dict]:
    node = nuxt_data(page_html)
    for key in LIST_PATH:
        node = node.get(key) if isinstance(node, dict) else None
    if not isinstance(node, list):
        raise ParseError(f"нет списка {'.'.join(LIST_PATH)}")
    return [j for j in node if isinstance(j, dict)]


def _seniority(grades) -> str | None:
    ranks = [_GRADES.get(str(g.get("name")).lower()) for g in grades or [] if isinstance(g, dict)]
    ranks = [r for r in ranks if r]
    return _LEVELS[max(ranks)] if ranks else None


def _format(values) -> str | None:
    values = [str(v) for v in values or []] if isinstance(values, list) else []
    for wanted in ("remote", "hybrid", "office"):
        if wanted in values:
            return wanted
    return None


def _scope(item: dict) -> tuple[str, list[str]]:
    if item.get("remote_type") == "global" or item.get("location_scope") == "anywhere":
        return "worldwide", []
    names = [str(n) for n in item.get("eligible_countries") or []]
    names += [str(r.get("name_en")) for r in item.get("regions") or [] if isinstance(r, dict)]
    codes, _ = countries_from(names)  # unknown names (e.g. Turkmenistan) can only widen, never hide KZ
    return ("countries", codes) if codes else ("unknown", [])


def _amount(v) -> int | None:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


class Hirify(Source):
    name = "hirify"
    lang = "ru"
    full_listing = False
    method = "JSON сайта"

    def parse_item(self, item: dict) -> Job | None:
        slug, title = item.get("slug"), item.get("title")
        if not slug or not title or item.get("id") is None:
            return None
        if item.get("suppress_distribution") or item.get("is_archived") or item.get("is_scam"):
            return None  # demo/test vacancies, archived, scam-flagged
        scope, codes = _scope(item)
        sal = item.get("salary") if isinstance(item.get("salary"), dict) else {}
        lo, hi = _amount(sal.get("min")), _amount(sal.get("max"))
        has_salary = lo is not None or hi is not None
        tldr = item.get("tldr") or ""
        regions = [str(r.get("name")) for r in item.get("regions") or [] if isinstance(r, dict) and r.get("name")]
        tags = [str(t.get("name")) for t in item.get("tags") or [] if isinstance(t, dict) and t.get("name")]
        return Job(
            source=self.name, source_id=str(item["id"]), url=JOB_URL.format(slug=slug), title=title,
            company=item.get("company_title"), lang=self.lang,
            description_html=f"<p>{_html.escape(tldr)}</p>" if tldr else "", description_text=tldr,
            salary_min=lo, salary_max=hi,
            salary_currency=sal.get("currency") if has_salary else None,
            salary_period=_PERIODS.get(str(sal.get("salary_period")).lower()) if has_salary else None,
            location_raw=", ".join(regions) or None, work_format=_format(item.get("work_format")),
            remote_scope=scope, countries=codes, seniority=_seniority(item.get("grades")),
            stack=tags, published_at=utc_from_iso(item.get("created_at")), raw=item)

    def _describe(self, client: PoliteClient, job: Job) -> None:
        try:
            data = nuxt_data(client.get(job.url).text)["data"]
            vacancy = next(v for k, v in data.items() if k.startswith("vacancy-"))
            text = vacancy.get("text")
        except SourceError as e:
            log.info("%s: описание %s не загружено: %s", self.name, job.source_id, e)
            return
        except (ParseError, KeyError, TypeError, AttributeError, StopIteration) as e:
            log.warning("%s: формат страницы вакансии %s изменился: %r", self.name, job.source_id, e)
            return
        if isinstance(text, str) and text.strip():
            job.description_html = text
            job.description_text = ""  # recomputed from the full HTML by normalize

    def fetch(self, client: PoliteClient, known: set[str], wants, settings: dict) -> list[Job]:
        out: dict[str, Job] = {}
        for spec in SPECIALIZATIONS:
            def page(n: int, spec=spec) -> list[dict]:
                params = {"work_format": "remote", "vacancy_language": "ru",
                          "hide_global_vacancies": "1", "specializations": spec}
                return parse_payload(client.get(URL, params=params).text)

            for job in paged(page, self.parse_item, known, 1):
                out.setdefault(job.source_id, job)
        jobs = list(out.values())
        for job in jobs:
            if job.source_id not in known and wants(job):
                self._describe(client, job)
        return jobs


SOURCE = register(Hirify())
