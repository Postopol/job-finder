from __future__ import annotations

import html as _html

from ..http import PoliteClient
from ..models import Job
from . import register
from .base import ParseError, Source, next_data, paged
from .geo import countries_from, scope_from_location, utc_from_iso

URL = "https://www.remoterocketship.com/country/worldwide/jobs/{role}"
ROLES = ("software-engineer", "backend-engineer", "frontend-engineer", "devops", "data-engineer")
LIST_PATH = ("props", "pageProps", "initialJobOpenings")
_PERIODS = {"per year": "year", "per month": "month", "per hour": "hour"}


def parse_payload(page_html: str) -> list[dict]:
    node = next_data(page_html)
    for key in LIST_PATH:
        node = node.get(key) if isinstance(node, dict) else None
    if not isinstance(node, list):
        raise ParseError(f"нет списка {'.'.join(LIST_PATH)}")
    return [j for j in node if isinstance(j, dict)]


def _seniority(item: dict) -> str | None:
    for flag, level in (("isLead", "lead"), ("isSenior", "senior"), ("isJunior", "junior"),
                        ("isEntryLevel", "junior"), ("isMidLevel", "middle")):
        if item.get(flag):
            return level
    return None


def _amount(v) -> int | None:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


def _url(item: dict) -> str | None:
    company = item.get("company")
    slug = company.get("slug") if isinstance(company, dict) else None
    if slug and item.get("slug"):
        return f"https://www.remoterocketship.com/us/company/{slug}/jobs/{item['slug']}/"
    apply = item.get("url")
    return apply if isinstance(apply, str) and apply.startswith("https://") else None


class RemoteRocketship(Source):
    name = "rocketship"
    lang = "en"
    full_listing = False
    method = "JSON сайта"

    def parse_item(self, item: dict) -> Job | None:
        title, url = item.get("roleTitle"), _url(item)
        if not title or not url or item.get("id") is None:
            return None
        location = item.get("location") if isinstance(item.get("location"), str) else None
        names = [str(n) for n in item.get("locationCountries") or []]
        if names:
            codes, unknown = countries_from(names)
            scope, codes = ("unknown", []) if unknown or not codes else ("countries", codes)
        else:
            scope, codes = scope_from_location(location)
        sal = item.get("salaryRange") if isinstance(item.get("salaryRange"), dict) else {}
        lo, hi = _amount(sal.get("min")), _amount(sal.get("max"))
        has_salary = lo is not None or hi is not None
        summary = item.get("twoLineJobDescriptionSummary") or item.get("jobDescriptionSummary") or ""
        company = item.get("company")
        return Job(
            source=self.name, source_id=str(item["id"]), url=url, title=title,
            company=company.get("name") if isinstance(company, dict) else None, lang=self.lang,
            description_html=f"<p>{_html.escape(summary)}</p>" if summary else "",
            description_text=summary,
            salary_min=lo, salary_max=hi,
            salary_currency=sal.get("currencyCode") if has_salary else None,
            salary_period=_PERIODS.get(str(sal.get("salaryType")).lower()) if has_salary else None,
            location_raw=location, work_format="remote", remote_scope=scope, countries=codes,
            seniority=_seniority(item),
            stack=[str(t) for t in item.get("techStack") or []],
            published_at=utc_from_iso(item.get("created_at")), raw=item)

    def fetch(self, client: PoliteClient, known: set[str], wants, settings: dict) -> list[Job]:
        out: dict[str, Job] = {}
        for role in ROLES:
            def page(n: int, role=role) -> list[dict]:
                return parse_payload(client.get(URL.format(role=role)).text)

            for job in paged(page, self.parse_item, known, 1):
                out.setdefault(job.source_id, job)
        return list(out.values())


SOURCE = register(RemoteRocketship())
