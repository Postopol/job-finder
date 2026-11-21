from __future__ import annotations

from ..http import PoliteClient
from ..models import Job
from . import register
from .base import Source, paged
from .geo import countries_from, utc_from_epoch

URL = "https://himalayas.app/jobs/api/search"
TERMS = ("developer", "engineer", "devops", "data")
_PERIODS = {"annual": "year", "yearly": "year", "monthly": "month", "hourly": "hour",
            "weekly": None, "daily": None}


def parse_payload(payload) -> list[dict]:
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    return [j for j in jobs if isinstance(j, dict)] if isinstance(jobs, list) else []


def _tz(offsets) -> list[str]:
    if not isinstance(offsets, list) or len(offsets) >= 30:  # all zones = no restriction
        return []
    return [f"UTC{o:+g}" for o in offsets if isinstance(o, (int, float))]


def _amount(v) -> int | None:
    return int(v) if isinstance(v, (int, float)) and v > 0 else None


class Himalayas(Source):
    name = "himalayas"
    lang = "en"
    full_listing = False
    method = "Открытый API"

    def parse_item(self, item: dict) -> Job | None:
        url = item.get("guid") or item.get("applicationLink")
        title = item.get("title")
        if not url or not title:
            return None
        names = [str(n) for n in item.get("locationRestrictions") or []]
        codes, unknown = countries_from(names)
        if unknown:  # never return a narrower country list than the site gave
            codes = []
        scope = "worldwide" if not names else ("countries" if codes else "unknown")
        lo, hi = _amount(item.get("minSalary")), _amount(item.get("maxSalary"))
        has_salary = lo is not None or hi is not None
        return Job(
            source=self.name, source_id=url, url=url, title=title,
            company=item.get("companyName"), lang=self.lang,
            description_html=item.get("description") or "",
            salary_min=lo, salary_max=hi,
            salary_currency=item.get("currency") if has_salary else None,
            salary_period=_PERIODS.get(str(item.get("salaryPeriod")).lower()) if has_salary else None,
            location_raw=", ".join(names) or None, work_format="remote",
            remote_scope=scope, countries=codes, timezones=_tz(item.get("timezoneRestrictions")),
            stack=[], published_at=utc_from_epoch(item.get("pubDate")), raw=item)

    def fetch(self, client: PoliteClient, known: set[str], wants, settings: dict) -> list[Job]:
        out: dict[str, Job] = {}
        for term in TERMS:
            def page(n: int, term=term) -> list[dict]:
                params = {"worldwide": "true", "q": term}
                if n > 1:
                    params["page"] = n
                return parse_payload(client.get(URL, params=params).json())

            for job in paged(page, self.parse_item, known, int(settings.get("max_pages", 5))):
                out.setdefault(job.source_id, job)
        return list(out.values())


SOURCE = register(Himalayas())
