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

HYBRID_RE = re.compile(r"(?<!\w)(?:hybrid|гибрид\w*)(?!\w)", re.IGNORECASE)
OFFICE_RE = re.compile(r"(?<!\w)(?:on-site|onsite|офис\w*)(?!\w)", re.IGNORECASE)
REMOTE_RE = re.compile(r"(?<!\w)(?:remote|удал[её]н\w*)(?!\w)", re.IGNORECASE)


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
    if job.remote_scope not in ("unknown", "countries"):
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
    if HYBRID_RE.search(text):
        return "hybrid"
    if OFFICE_RE.search(text) and not REMOTE_RE.search(text):
        return "office"

    if job.remote_scope == "restricted":
        return "restricted"
    if job.remote_scope == "countries" and job.countries and cfg.country not in job.countries:
        return "restricted"

    haystack = f"{job.title} {job.description_text or ''}"
    for w in cfg.stopwords:
        if w and _has(haystack, w):
            return f"stopword:{w.lower()}"
    return None


NON_IT_TITLE_WORDS = [
    "sales", "account executive", "account manager", "account director",
    "business development", "marketing", "communications", "customer success",
    "customer support", "customer service", "support engineer", "support specialist",
    "technical support", "presales", "pre-sales", "solutions engineer",
    "solutions consultant", "recruiter", "talent", "hr", "people partner", "accountant",
    "accounting", "finance", "legal", "counsel", "clinical", "nurse", "therapist",
    "medical", "physician", "teacher", "tutor", "art director", "creative director",
    "copywriter", "content writer", "office manager", "executive assistant",
    "operations manager",
]
_NON_IT_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(w) for w in NON_IT_TITLE_WORDS) + r")(?!\w)",
    re.IGNORECASE)


def is_non_it_title(title: str) -> bool:
    """True when the title names a clearly non-IT role (sales, support, HR, ...)."""
    return _NON_IT_RE.search(title or "") is not None
