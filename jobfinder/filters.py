from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import CIS, Job

RESTRICTED = ["us only", "usa only", "u.s. only", "must be based in the us",
              "must reside in", "eu only", "europe only", "uk only",
              "только рф", "гражданство рф", "только россия",
              "only candidates from"]
WORLDWIDE = ["worldwide", "anywhere", "work from anywhere", "global",
             "весь мир", "любой стране", "любая страна"]
CIS_PHRASES = ["снг", "cis", "казахстан", "kazakhstan", "из любой точки снг"]

HYBRID_WORDS = ["hybrid", "гибрид"]
OFFICE_WORDS = ["on-site", "onsite", "в офисе", "офис"]


@dataclass
class FilterConfig:
    country: str = "KZ"
    stopwords: list[str] = field(default_factory=list)


def _has(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, re.IGNORECASE) is not None


def _any(text: str, phrases: list[str]) -> bool:
    return any(_has(text, p) for p in phrases)


def classify_scope(job: Job) -> tuple[str, list[str]]:
    if job.countries:
        scope = "cis" if all(c in CIS for c in job.countries) else "countries"
        return scope, list(job.countries)
    if job.remote_scope != "unknown":
        return job.remote_scope, []

    loc = job.location_raw or ""
    desc = job.description_text or ""
    full = f"{job.title} {loc} {desc}"

    if _any(f"{loc} {desc[:400]}", RESTRICTED):
        return "restricted", []
    if _any(full, WORLDWIDE):
        return "worldwide", []
    if _any(full, CIS_PHRASES):
        return "cis", []
    if _any(full, RESTRICTED):
        return "restricted", []
    return "unknown", []


def hidden_reason(job: Job, cfg: FilterConfig) -> str | None:
    if job.work_format in ("hybrid", "office"):
        return job.work_format
    text = f"{job.location_raw or ''} {job.title}"
    if _any(text, HYBRID_WORDS):
        return "hybrid"
    if _any(text, OFFICE_WORDS):
        return "office"

    if job.remote_scope == "restricted":
        return "restricted"
    if job.remote_scope == "countries" and cfg.country not in job.countries:
        return "restricted"

    haystack = f"{job.title} {job.description_text or ''}"
    for w in cfg.stopwords:
        if w and _has(haystack, w):
            return f"stopword:{w.lower()}"
    return None
