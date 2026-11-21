from __future__ import annotations

import html as htmllib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ..http import PoliteClient
from ..models import Job
from ..normalize import html_to_text
from . import register
from .base import ParseError, Source
from .geo import scope_from_location, utc_from_epoch, utc_from_iso

STORIES_URL = ("https://hn.algolia.com/api/v1/search_by_date"
               "?tags=story,author_whoishiring&hitsPerPage=5")
COMMENTS_URL = "https://hn.algolia.com/api/v1/search?tags=comment,story_{id}&hitsPerPage=1000"
ITEM_URL = "https://news.ycombinator.com/item?id={id}"
TITLE_PREFIX = "ask hn: who is hiring?"
REFRESH = timedelta(hours=24)


def latest_story_id(payload) -> str:
    """Newest «Ask HN: Who is hiring?» story id from the search_by_date response."""
    hits = payload.get("hits") if isinstance(payload, dict) else None
    if not isinstance(hits, list):
        raise ParseError("HN вернул неожиданный ответ")
    for h in hits:
        if isinstance(h, dict) and str(h.get("title") or "").lower().startswith(TITLE_PREFIX):
            return str(h["objectID"])
    raise ParseError("нет темы «Who is hiring?»")


def parse_payload(payload) -> list[dict]:
    """Top-level comments of the thread (replies and empty/deleted ones are dropped)."""
    hits = payload.get("hits") if isinstance(payload, dict) else None
    if not isinstance(hits, list):
        raise ParseError("HN вернул неожиданный ответ")
    return [h for h in hits
            if isinstance(h, dict) and h.get("objectID") and h.get("comment_text")
            and h.get("parent_id") == h.get("story_id")]


def _first_line(comment_html: str) -> str:
    head = comment_html.split("<p>", 1)[0]
    return " ".join(htmllib.unescape(head).split())


class HackerNews(Source):
    name = "hn"
    lang = "en"
    full_listing = True
    method = "Открытый API"

    def __init__(self, now: Callable[[], datetime] | None = None):
        self._now = now or (lambda: datetime.now(UTC))

    def parse_item(self, item: dict) -> Job | None:
        try:
            oid, body = item.get("objectID"), item.get("comment_text")
            if not oid or not body or "remote" not in html_to_text(body).lower():
                return None
            line = _first_line(body)
            if not line or line.lower().startswith("seeking"):
                return None
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) >= 2:
                company, title, rest = parts[0], parts[1], parts[2:]
                location = next((p for p in rest if "remote" in p.lower()),
                                rest[0] if rest else None)
            else:
                company, title, location = None, line[:150], None
            scope, codes = scope_from_location(location)
            return Job(
                source=self.name, source_id=str(oid), url=ITEM_URL.format(id=oid),
                title=title, company=company, lang=self.lang, description_html=body,
                description_text=html_to_text(body), location_raw=location,
                work_format="remote" if location and "remote" in location.lower() else None,
                remote_scope=scope, countries=codes,
                published_at=utc_from_epoch(item.get("created_at_i")), raw=item)
        except Exception:  # noqa: BLE001 - an odd item must not kill the run
            return None

    def fetch(self, client: PoliteClient, known: set[str], wants, settings: dict) -> list[Job]:
        story = latest_story_id(client.get(STORIES_URL).json())
        now = self._now()
        last = utc_from_iso(settings.get("hn_last_fetch"))
        if story == settings.get("hn_last_story") and last and now - last < REFRESH:
            return []
        url = COMMENTS_URL.format(id=story)
        payload = client.get(url).json()
        items = parse_payload(payload)
        pages = payload.get("nbPages") if isinstance(payload, dict) else 1
        limit = min(int(pages or 1), int(settings.get("max_pages") or 5))
        for page in range(1, limit):
            items += parse_payload(client.get(f"{url}&page={page}").json())
        settings["hn_last_story"] = story
        settings["hn_last_fetch"] = now.isoformat()
        return [j for j in map(self.parse_item, items) if j is not None]


SOURCE = register(HackerNews())
