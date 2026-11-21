from __future__ import annotations

import re

from ..http import PoliteClient
from ..models import Job
from . import register
from .base import Source
from .feed import entry_published, feed_entries
from .geo import utc_from_iso

# Feeds verified on remotefirstjobs.com (the site has /rss/jobs/<slug>.rss for each).
SLUGS = ("software-development", "devops", "data", "data-science", "qa")
URL = "https://remotefirstjobs.com/rss/jobs/{slug}.rss"
_COMPANY = re.compile(r"/companies/([^/]+)/")


def parse_payload(payload) -> list[dict]:
    out = []
    for e in feed_entries(payload):
        pub = entry_published(e)
        out.append({"title": e.get("title"), "link": e.get("link"),
                    "description": e.get("summary") or "",
                    "published_at": pub.isoformat() if pub else None})
    return out


class RemoteFirstJobs(Source):
    name = "remotefirst"
    lang = "en"
    full_listing = True
    method = "RSS"

    def parse_item(self, item: dict) -> Job | None:
        try:
            link, raw_title = item.get("link"), (item.get("title") or "").strip()
            if not link or not raw_title:
                return None
            role, sep, company = raw_title.rpartition(" at ")
            if not sep or not role.strip() or not company.strip():
                role, company = raw_title, None
                m = _COMPANY.search(link)
                if m:
                    company = m.group(1).replace("-", " ").title()
            return Job(
                source=self.name, source_id=link.rstrip("/").rsplit("/", 1)[-1], url=link,
                title=role.strip(), company=company.strip() if company else None,
                lang=self.lang, description_html=item.get("description") or "",
                work_format="remote", remote_scope="unknown",
                published_at=utc_from_iso(item.get("published_at")), raw=item)
        except Exception:  # noqa: BLE001 - an odd item must not kill the run
            return None

    def fetch(self, client: PoliteClient, known: set[str], wants, settings: dict) -> list[Job]:
        seen: set[str] = set()
        out: list[Job] = []
        for slug in SLUGS:
            for item in parse_payload(client.get(URL.format(slug=slug)).text):
                link = item.get("link")
                if link in seen:
                    continue
                seen.add(link)
                job = self.parse_item(item)
                if job is not None:
                    out.append(job)
        return out


SOURCE = register(RemoteFirstJobs())
