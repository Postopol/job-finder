from __future__ import annotations

import re

from ..filters import is_non_it_title
from ..http import PoliteClient
from ..models import Job
from . import register
from .base import ParseError, Source
from .geo import scope_from_location, utc_from_epoch

URL = "https://remoteok.com/api"
IT_TAGS = {
    "dev", "developer", "devops", "programming", "software", "sys admin", "sysadmin",
    "backend", "frontend", "front end", "full stack", "fullstack", "web dev", "qa",
    "testing", "quality assurance", "infosec", "cloud", "mobile", "embedded", "python",
    "golang", "java", "javascript", "typescript", "react", "node", "nodejs", "php", "ruby",
    "rust", "c plus plus", "c sharp", "dotnet", "swift", "kotlin", "scala", "elixir", "aws",
    "kubernetes", "docker", "postgres", "sql", "machine learning",
}
_DEV_TITLE = re.compile(
    r"developer|engineer|programmer|devops|\bsre\b|architect|data scientist|\bml\b|\bqa\b|tester",
    re.I)


def parse_payload(payload) -> list[dict]:
    if not isinstance(payload, list):
        raise ParseError("RemoteOK вернул не список")
    return [i for i in payload if isinstance(i, dict) and "legal" not in i and i.get("id")]


def _amount(v) -> int | None:
    return int(v) if isinstance(v, (int, float)) and v > 0 else None


class RemoteOK(Source):
    name = "remoteok"
    lang = "en"
    full_listing = True
    method = "Открытый API"

    def parse_item(self, item: dict) -> Job | None:
        url, title = item.get("url") or item.get("apply_url"), item.get("position")
        if not url or not title or not item.get("id"):
            return None
        tags = [str(t) for t in item.get("tags") or []]
        if is_non_it_title(title) or not (any(t.lower() in IT_TAGS for t in tags) or _DEV_TITLE.search(title)):
            return None
        lo, hi = _amount(item.get("salary_min")), _amount(item.get("salary_max"))
        scope, codes = scope_from_location(item.get("location"))
        return Job(
            source=self.name, source_id=str(item["id"]), url=url, title=title,
            company=item.get("company"), lang=self.lang,
            description_html=item.get("description") or "",
            salary_min=lo, salary_max=hi,
            salary_currency="USD" if lo or hi else None,
            salary_period="year" if lo or hi else None,
            location_raw=item.get("location") or None, work_format="remote",
            remote_scope=scope, countries=codes,
            stack=tags,
            published_at=utc_from_epoch(item.get("epoch")), raw=item)

    def fetch(self, client: PoliteClient, known: set[str], wants, settings: dict) -> list[Job]:
        items = parse_payload(client.get(URL).json())
        return [j for j in map(self.parse_item, items) if j is not None]


SOURCE = register(RemoteOK())
