from __future__ import annotations

from ..http import PoliteClient
from ..models import Job
from . import register
from .base import ParseError, Source
from .geo import scope_from_location, utc_from_iso

URL = "https://jobicy.com/api/v2/remote-jobs"
# IT slugs from ?get=industries: Software Engineering, DevOps & Infrastructure,
# Data Science & Analytics, QA & Testing, Cybersecurity
INDUSTRIES = ("engineering", "admin", "data-science", "qa-testing", "cybersecurity")
_PERIODS = {"yearly": "year", "monthly": "month", "hourly": "hour"}


def parse_payload(payload) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ParseError("нет списка jobs в ответе Jobicy")
    return [j for j in payload["jobs"] if isinstance(j, dict)]


def _amount(v) -> int | None:
    return int(v) if isinstance(v, (int, float)) and v > 0 else None


class Jobicy(Source):
    name = "jobicy"
    lang = "en"
    full_listing = True
    method = "Открытый API"

    def parse_item(self, item: dict) -> Job | None:
        url, title = item.get("url"), item.get("jobTitle")
        if not url or not title or not item.get("id"):
            return None
        geo = item.get("jobGeo")
        if isinstance(geo, list):
            geo = ", ".join(map(str, geo))
        scope, codes = scope_from_location(geo)
        lo, hi = _amount(item.get("salaryMin")), _amount(item.get("salaryMax"))
        has = lo is not None or hi is not None
        return Job(
            source=self.name, source_id=str(item["id"]), url=url, title=title,
            company=item.get("companyName"), lang=self.lang,
            description_html=item.get("jobDescription") or "",
            salary_min=lo, salary_max=hi,
            salary_currency=item.get("salaryCurrency") if has else None,
            salary_period=_PERIODS.get(str(item.get("salaryPeriod")).lower()) if has else None,
            location_raw=geo or None, work_format="remote",
            remote_scope=scope, countries=codes,
            published_at=utc_from_iso(item.get("pubDate")), raw=item)

    def fetch(self, client: PoliteClient, known: set[str], wants, settings: dict) -> list[Job]:
        out: dict[str, Job] = {}
        for slug in INDUSTRIES:
            items = parse_payload(client.get(URL, params={"count": 100, "industry": slug}).json())
            for item in items:
                job = self.parse_item(item)
                if job is not None:
                    out.setdefault(job.source_id, job)
        return list(out.values())


SOURCE = register(Jobicy())
