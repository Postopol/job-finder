from __future__ import annotations

import re

from ..http import PoliteClient
from ..models import Job
from . import register
from .base import Source
from .feed import entry_published, feed_entries
from .geo import utc_from_iso

URL = "https://weworkremotely.com/remote-jobs.rss"
IT_CATEGORIES = {"back-end programming", "front-end programming", "full-stack programming",
                 "devops and sysadmin"}
_FLAGS = re.compile(r"[\U0001F1E6-\U0001F1FF]")


def parse_payload(payload) -> list[dict]:
    out = []
    for e in feed_entries(payload):
        tags = e.get("tags") or []
        out.append({
            "title": e.get("title"), "link": e.get("link"),
            "region": e.get("region") or "", "country": e.get("country") or "",
            "state": e.get("state") or "", "category": tags[0].get("term") if tags else "",
            "type": e.get("type") or "", "description": e.get("summary") or "",
            "published": e.get("published") or "",
            "published_at": entry_published(e).isoformat() if entry_published(e) else None,
        })
    return out


def _scope(region: str) -> str:
    r = region.strip().lower()
    if r.startswith("anywhere"):
        return "worldwide"
    return "restricted" if r.endswith(" only") else "unknown"


class WeWorkRemotely(Source):
    name = "wwr"
    lang = "en"
    full_listing = True
    method = "RSS"

    def parse_item(self, item: dict) -> Job | None:
        try:
            link, raw_title = item.get("link"), (item.get("title") or "").strip()
            if not link or not raw_title:
                return None
            if str(item.get("category") or "").strip().lower() not in IT_CATEGORIES:
                return None
            company, sep, role = raw_title.partition(": ")
            if not sep or not role.strip():
                company, role = None, raw_title
            region = str(item.get("region") or "").strip()
            country = re.sub(r"\s+", " ", _FLAGS.sub("", str(item.get("country") or ""))).strip()
            location = ", ".join(p for p in (region, country) if p) or None
            return Job(
                source=self.name, source_id=link.rstrip("/").rsplit("/", 1)[-1], url=link,
                title=role.strip(), company=company.strip() if company else None,
                lang=self.lang, description_html=item.get("description") or "",
                location_raw=location, work_format="remote", remote_scope=_scope(region),
                published_at=utc_from_iso(item.get("published_at")), raw=item)
        except Exception:  # noqa: BLE001 - an odd item must not kill the run
            return None

    def fetch(self, client: PoliteClient, known: set[str], wants, settings: dict) -> list[Job]:
        items = parse_payload(client.get(URL).text)
        return [j for j in map(self.parse_item, items) if j is not None]


SOURCE = register(WeWorkRemotely())
