from __future__ import annotations

import re

from ..http import PoliteClient
from ..models import Job
from . import register
from .base import ParseError, Source
from .geo import scope_from_location, utc_from_iso

URL = "https://www.workingnomads.com/api/exposed_jobs/"
IT_CATEGORIES = {"development", "devops", "devops & sysadmin", "sysadmin", "data",
                 "data science", "qa", "cyber security", "cybersecurity"}
_UI_DEV = re.compile(r"\b(?:ui|ux|front[- ]?end|web)\b", re.I)


def parse_payload(payload) -> list[dict]:
    if not isinstance(payload, list):
        raise ParseError("Working Nomads вернул не список")
    return [i for i in payload if isinstance(i, dict)]


class WorkingNomads(Source):
    name = "workingnomads"
    lang = "en"
    full_listing = True
    method = "Открытый API"

    def parse_item(self, item: dict) -> Job | None:
        url, title = item.get("url"), item.get("title")
        if not url or not title:
            return None
        cat = str(item.get("category_name") or "").strip().lower()
        if cat not in IT_CATEGORIES and not (cat == "design" and _UI_DEV.search(title)):
            return None
        loc = item.get("location") or None
        scope, codes = scope_from_location(loc)
        tags = [t.strip() for t in str(item.get("tags") or "").split(",") if t.strip()]
        return Job(
            source=self.name, source_id=url.rstrip("/").rsplit("/", 1)[-1],
            url=url, title=title, company=item.get("company_name"), lang=self.lang,
            description_html=item.get("description") or "",
            location_raw=loc, work_format="remote", remote_scope=scope, countries=codes,
            stack=tags, published_at=utc_from_iso(item.get("pub_date")), raw=item)

    def fetch(self, client: PoliteClient, known: set[str], wants, settings: dict) -> list[Job]:
        items = parse_payload(client.get(URL).json())
        return [j for j in map(self.parse_item, items) if j is not None]


SOURCE = register(WorkingNomads())
