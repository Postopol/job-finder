"""Shared RSS helpers: feedparser works on text that PoliteClient already downloaded."""
from __future__ import annotations

import calendar
from datetime import UTC, datetime

import feedparser

from .base import ParseError


def feed_entries(content: str | bytes) -> list:
    """Parse feed text; ParseError when it is not a feed at all."""
    d = feedparser.parse(content)
    if not d.entries and (d.bozo or not d.get("version")):
        raise ParseError("ответ не похож на RSS")
    return list(d.entries)


def entry_published(entry) -> datetime | None:
    st = entry.get("published_parsed") or entry.get("updated_parsed")
    if not st:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(st), UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
